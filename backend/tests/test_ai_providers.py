"""AI providers without a network: request shape, structured output, refusals and errors."""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel

from glasshaus.ai import providers
from glasshaus.ai.providers import AnthropicProvider, FakeProvider, OpenAICompatibleProvider
from glasshaus.config import Settings
from glasshaus.core.errors import RateLimited, Unavailable


class Out(BaseModel):
    headline: str
    items: list[str]


def settings(**kw: Any) -> Settings:
    return Settings(env="test", secret_key="x" * 40, **kw)


def message(text: str, stop: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text=text)],
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=12, output_tokens=7),
    )


async def test_anthropic_request_shape_and_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    p = AnthropicProvider(settings(ai_provider="anthropic", ai_api_key="sk-test"))
    seen: dict[str, Any] = {}

    async def create(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return message(json.dumps({"headline": "On track", "items": ["a"]}))

    monkeypatch.setattr(p.client.beta.messages, "create", create)
    result = await p.complete(system="sys", prompt="hi", output=Out, max_tokens=100)
    assert result.output == Out(headline="On track", items=["a"])
    assert (result.input_tokens, result.output_tokens) == (12, 7)
    assert seen["model"] == "claude-opus-5-5"
    assert seen["fallbacks"] == "default" and seen["betas"] == ["server-side-fallback-2026-07-01"]
    fmt = seen["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert "effort" not in seen["output_config"]
    assert "thinking" not in seen


async def test_anthropic_options_refusal_and_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    p = AnthropicProvider(
        settings(ai_provider="anthropic", ai_api_key="k", ai_fallbacks=False, ai_effort="low", ai_model="m")
    )
    replies = iter([message("", "refusal"), message('{"headline": "x"', "max_tokens")])
    seen: dict[str, Any] = {}

    async def create(**kwargs: Any) -> SimpleNamespace:
        seen.update(kwargs)
        return next(replies)

    monkeypatch.setattr(p.client.beta.messages, "create", create)
    with pytest.raises(Unavailable, match="declined"):
        await p.complete(system="s", prompt="p", output=Out, max_tokens=10)
    assert (
        seen["fallbacks"] is anthropic.omit
        and seen["output_config"]["effort"] == "low"
        and seen["model"] == "m"
    )
    with pytest.raises(Unavailable, match="cut off"):
        await p.complete(system="s", prompt="p", output=Out, max_tokens=10)


async def test_anthropic_errors_map_to_service_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    p = AnthropicProvider(settings(ai_provider="anthropic", ai_api_key="k"))
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def status(code: int) -> httpx2.Response:
        return httpx2.Response(code, request=request, json={"error": {"message": "nope"}})

    for exc, expected in (
        (anthropic.AuthenticationError("bad", response=status(401), body=None), Unavailable),
        (anthropic.RateLimitError("slow", response=status(429), body=None), RateLimited),
        (anthropic.APIConnectionError(request=request), Unavailable),
    ):

        async def create(_exc: Exception = exc, **_: Any) -> None:
            raise _exc

        monkeypatch.setattr(p.client.beta.messages, "create", create)
        with pytest.raises(expected):
            await p.complete(system="s", prompt="p", output=Out, max_tokens=10)


async def test_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        content = 'Sure! ```json\n{"headline": "Fine", "items": []}\n```'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "model": "llama"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = OpenAICompatibleProvider(
        settings(ai_provider="openai", ai_base_url="http://ollama:11434/v1/", ai_api_key="t")
    )
    result = await p.complete(system="s", prompt="p", output=Out, max_tokens=50)
    assert result.output.headline == "Fine" and result.model == "llama"
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "http://ollama:11434/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer t"
    assert body["response_format"]["type"] == "json_schema" and body["model"] == "llama3.1"

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": "not json"}}]})), **kw),
    )  # fmt: skip
    with pytest.raises(Unavailable, match="expected format"):
        await p.complete(system="s", prompt="p", output=Out, max_tokens=50)
    with pytest.raises(Unavailable, match="BASE_URL"):
        OpenAICompatibleProvider(settings(ai_provider="openai"))


async def test_fake_provider_builds_schema_valid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeProvider()
    result = await fake.complete(system="s", prompt="p", output=Out, max_tokens=10)
    assert result.output.items == ["Example items"]
    monkeypatch.setitem(providers.FAKE_RESPONSES, "Out", {"headline": "Canned", "items": []})
    assert (
        await fake.complete(system="s", prompt="p", output=Out, max_tokens=10)
    ).output.headline == "Canned"
    assert [c["output"] for c in fake.calls] == ["Out", "Out"]


async def test_anthropic_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    p = AnthropicProvider(settings(ai_provider="anthropic", ai_api_key=""))
    with pytest.raises(Unavailable, match="GLASSHAUS_AI_API_KEY"):
        await p.complete(system="s", prompt="p", output=Out, max_tokens=10)


async def test_openai_provider_with_azure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure OpenAI: api-key header, optional api-version, and max_completion_tokens for newer models."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if "max_tokens" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'max_tokens'. "
                                                       "Use 'max_completion_tokens' instead."}})  # fmt: skip
        content = json.dumps({"headline": "Azure", "items": []})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}], "model": "gpt-5-mini"}
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = OpenAICompatibleProvider(
        settings(
            ai_provider="openai",
            ai_base_url="https://acme.openai.azure.com/openai/deployments/glasshaus",
            ai_model="glasshaus",
            ai_api_key="azure-key",
            ai_auth_header="api-key",
            ai_api_version="2024-10-21",
        )
    )
    result = await p.complete(system="s", prompt="p", output=Out, max_tokens=50)
    assert result.output.headline == "Azure" and result.model == "gpt-5-mini"
    assert len(seen) == 2
    first, retry = seen
    assert str(first.url) == (
        "https://acme.openai.azure.com/openai/deployments/glasshaus/chat/completions?api-version=2024-10-21"
    )
    assert first.headers["api-key"] == "azure-key" and "authorization" not in first.headers
    assert json.loads(retry.content)["max_completion_tokens"] == 50
    assert "max_tokens" not in json.loads(retry.content)
