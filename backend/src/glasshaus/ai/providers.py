"""AI providers behind one interface: Claude (Anthropic SDK), any OpenAI-compatible endpoint (Ollama,
LM Studio, vLLM...), and a fake provider for demos and tests.

A provider takes a system prompt, a user prompt and a Pydantic output model, and returns the
validated object. It never sees tools or credentials, and nothing it returns is acted on without a
person (or an MCP client) applying it through the normal service layer.
"""

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
import httpx
from anthropic.types.beta import BetaOutputConfigParam
from pydantic import BaseModel, ValidationError

from glasshaus.config import Settings, get_settings
from glasshaus.core.errors import RateLimited, Unavailable
from glasshaus.logs import get_logger

log = get_logger(__name__)

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "llama3.1", "fake": "fake"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Completion[T: BaseModel]:
    output: T
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    async def complete[T: BaseModel](
        self, *, system: str, prompt: str, output: type[T], max_tokens: int
    ) -> Completion[T]: ...


def json_schema(output: type[BaseModel]) -> dict[str, Any]:
    """Structured-output schema: every property required, no extra keys (unsupported keywords move
    into descriptions)."""
    return anthropic.transform_schema(output)


def _parse[T: BaseModel](output: type[T], text: str) -> T:
    try:
        return output.model_validate_json(text)
    except ValidationError:
        # Local models sometimes wrap JSON in prose or code fences.
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return output.model_validate_json(match.group(0))
            except ValidationError:
                pass
    raise Unavailable("the AI response did not match the expected format; try again")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.ai_model or DEFAULT_MODELS["anthropic"]
        self.effort = settings.ai_effort
        self.fallbacks = settings.ai_fallbacks
        key = (settings.ai_api_key.get_secret_value() if settings.ai_api_key else "") or None
        self.has_credentials = bool(
            key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        self.client = anthropic.AsyncAnthropic(
            api_key=key,  # None: the SDK reads ANTHROPIC_API_KEY
            base_url=settings.ai_base_url or None,
            timeout=settings.ai_timeout_seconds,
            max_retries=2,
        )

    async def complete[T: BaseModel](
        self, *, system: str, prompt: str, output: type[T], max_tokens: int
    ) -> Completion[T]:
        output_config: BetaOutputConfigParam = {
            "format": {"type": "json_schema", "schema": json_schema(output)}
        }
        if self.effort:
            output_config["effort"] = self.effort
        if not self.has_credentials:
            raise Unavailable("set GLASSHAUS_AI_API_KEY to a Claude API key to use the anthropic provider")
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
                # A declined request is re-run server-side on Anthropic's recommended fallback model.
                fallbacks="default" if self.fallbacks else anthropic.omit,
                betas=[FALLBACK_BETA] if self.fallbacks else anthropic.omit,
            )
        except anthropic.AuthenticationError:
            raise Unavailable("the AI provider rejected the API key; check GLASSHAUS_AI_API_KEY") from None
        except anthropic.PermissionDeniedError:
            raise Unavailable("the AI provider API key lacks permission for this model") from None
        except anthropic.NotFoundError:
            raise Unavailable(f"the AI provider does not know model '{self.model}'") from None
        except anthropic.RateLimitError:
            raise RateLimited("the AI provider is rate limiting requests; try again shortly") from None
        except anthropic.BadRequestError as exc:
            log.warning("ai.anthropic_bad_request", error=exc.message)
            raise Unavailable(f"the AI provider rejected the request: {exc.message}") from None
        except anthropic.APIStatusError as exc:
            raise Unavailable(f"the AI provider returned an error ({exc.status_code}); try again") from None
        except anthropic.APIConnectionError:
            raise Unavailable("could not reach the AI provider; try again") from None
        if response.stop_reason == "refusal":
            raise Unavailable("the AI model declined this request")
        if response.stop_reason == "max_tokens":
            raise Unavailable("the AI response was cut off; try a narrower request")
        text = next((b.text for b in response.content if b.type == "text"), "")
        usage = response.usage
        return Completion(
            output=_parse(output, text),
            model=response.model,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            extra={"request_id": getattr(response, "_request_id", None)},
        )


class OpenAICompatibleProvider:
    """Any server with an OpenAI-style ``/chat/completions`` endpoint (Ollama: http://ollama:11434/v1)."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_base_url:
            raise Unavailable(
                "set GLASSHAUS_AI_BASE_URL for the openai provider (e.g. http://ollama:11434/v1)"
            )
        self.model = settings.ai_model or DEFAULT_MODELS["openai"]
        self.url = settings.ai_base_url.rstrip("/") + "/chat/completions"
        self.timeout = settings.ai_timeout_seconds
        self.headers = {"Content-Type": "application/json"}
        if settings.ai_api_key and settings.ai_api_key.get_secret_value():
            self.headers["Authorization"] = f"Bearer {settings.ai_api_key.get_secret_value()}"

    async def complete[T: BaseModel](
        self, *, system: str, prompt: str, output: type[T], max_tokens: int
    ) -> Completion[T]:
        schema = json_schema(output)
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": f"{system}\n\nReply with JSON only, matching this schema:\n"
                 f"{json.dumps(schema)}"},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": output.__name__, "schema": schema},
            },
        }  # fmt: skip
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self.url, json=body, headers=self.headers)
        except httpx.HTTPError:
            raise Unavailable("could not reach the AI provider; try again") from None
        if r.status_code == 429:
            raise RateLimited("the AI provider is rate limiting requests; try again shortly")
        if r.status_code >= 400:
            log.warning("ai.openai_error", status=r.status_code, body=r.text[:300])
            raise Unavailable(f"the AI provider returned an error ({r.status_code})")
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise Unavailable("the AI provider returned an unexpected response") from None
        usage = data.get("usage") or {}
        return Completion(
            output=_parse(output, text),
            model=str(data.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


# Canned output for the fake provider, keyed by output model name (tests and demos override these).
FAKE_RESPONSES: dict[str, dict[str, Any]] = {}


def _example(schema: dict[str, Any], defs: dict[str, Any], name: str = "") -> Any:
    if "$ref" in schema:
        return _example(defs[schema["$ref"].rsplit("/", 1)[-1]], defs, name)
    if "anyOf" in schema:
        options = [s for s in schema["anyOf"] if s.get("type") != "null"]
        return _example(options[0], defs, name) if options else None
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {k: _example(v, defs, k) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [_example(schema.get("items", {}), defs, name)]
    if kind in ("integer", "number"):
        return 1
    if kind == "boolean":
        return False
    if schema.get("format") == "date":
        return None
    return f"Example {name.replace('_', ' ')}".strip()


class FakeProvider:
    """Deterministic output for demos, end-to-end tests and development without a model."""

    name = "fake"
    model = "fake"

    def __init__(self, settings: Settings | None = None) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete[T: BaseModel](
        self, *, system: str, prompt: str, output: type[T], max_tokens: int
    ) -> Completion[T]:
        self.calls.append({"system": system, "prompt": prompt, "output": output.__name__})
        canned = FAKE_RESPONSES.get(output.__name__)
        if canned is None:
            schema = json_schema(output)
            canned = _example(schema, schema.get("$defs", {}))
        return Completion(output=output.model_validate(canned), model="fake")


_provider: tuple[tuple[Any, ...], Provider] | None = None


def get_provider() -> Provider | None:
    """The configured provider, or None when the server has none. Built once per configuration."""
    global _provider
    settings = get_settings()
    if settings.ai_provider == "none":
        return None
    key = (
        settings.ai_provider,
        settings.ai_model,
        settings.ai_base_url,
        settings.ai_api_key,
        settings.ai_effort,
    )
    if _provider is None or _provider[0] != key:
        factories: dict[str, Callable[[Settings], Provider]] = {
            "anthropic": AnthropicProvider,
            "openai": OpenAICompatibleProvider,
            "fake": FakeProvider,
        }
        _provider = (key, factories[settings.ai_provider](settings))
    return _provider[1]


def model_name() -> str:
    settings = get_settings()
    if settings.ai_provider == "none":
        return ""
    return settings.ai_model or DEFAULT_MODELS[settings.ai_provider]


async def timed[T: BaseModel](
    provider: Provider, *, system: str, prompt: str, output: type[T], max_tokens: int
) -> Completion[T]:
    started = time.monotonic()
    result = await provider.complete(system=system, prompt=prompt, output=output, max_tokens=max_tokens)
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result
