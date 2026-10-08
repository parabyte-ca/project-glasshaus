#!/usr/bin/env python3
"""Example agent: drive Project Glasshaus through its MCP server only.

Creates two tasks, makes the second wait for the first, completes the first, and prints the
status-summary facts an LLM would turn into a weekly update. Every call is audited as you.

    pip install "mcp>=2.3"            # or: uv run --with "mcp>=2.3" examples/agent.py ...
    export GLASSHAUS_TOKEN=ghp_...    # Account > API tokens (read + write)
    python examples/agent.py --url http://localhost:8472/mcp --project WEB
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def call(client: Client, tool: str, **args: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, args)
    if result.is_error:
        text = " ".join(getattr(c, "text", "") for c in result.content)
        raise SystemExit(f"{tool} failed: {text}")
    data: dict[str, Any] = result.structured_content or {}
    return data


async def run(url: str, token: str, project: str) -> dict[str, Any]:
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60)
    async with Client(streamable_http_client(url, http_client=http)) as client:
        me = await call(client, "whoami")
        print(f"Connected as {me['user']['email']} with scopes {', '.join(me['scopes'])}", file=sys.stderr)

        design = (await call(client, "create_task", project=project, title="Design the API"))["task"]
        build = (await call(client, "create_task", project=project, title="Build the API"))["task"]
        await call(
            client, "manage_dependencies", action="add", predecessor=design["key"], successor=build["key"]
        )
        print(f"Created {design['key']} and {build['key']}; {build['key']} waits for it", file=sys.stderr)

        await call(client, "change_status", task=design["key"], status="done")
        summary = await call(client, "status_summary", project=project, days=7)
        return {"design": design["key"], "build": build["key"], "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default=os.getenv("GLASSHAUS_MCP_URL", "http://localhost:8472/mcp"))
    parser.add_argument("--project", required=True, help="Project key, e.g. WEB")
    args = parser.parse_args()
    token = os.getenv("GLASSHAUS_TOKEN")
    if not token:
        raise SystemExit("set GLASSHAUS_TOKEN to a Glasshaus API token")
    print(json.dumps(asyncio.run(run(args.url, token, args.project)), indent=2, default=str))


if __name__ == "__main__":
    main()
