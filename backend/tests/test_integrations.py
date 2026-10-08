"""The client configuration examples in docs/integrations stay valid and in step with the server."""

import json
import runpy
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "integrations"


def load(path: str) -> Any:
    return json.loads((DOCS / path).read_text())


def test_vscode_configs() -> None:
    for name in ("vscode/mcp.json", "vscode/mcp.token.json"):
        server = load(name)["servers"]["glasshaus"]
        assert server["type"] == "http" and server["url"].endswith(":8472/mcp")
    token = load("vscode/mcp.token.json")
    assert token["inputs"][0]["password"] is True
    assert token["servers"]["glasshaus"]["headers"]["Authorization"] == "Bearer ${input:glasshaus-token}"


def test_claude_configs() -> None:
    remote = load("claude/claude_desktop_config.json")["mcpServers"]["glasshaus"]
    assert remote["command"] == "npx" and any(a.endswith("/mcp") for a in remote["args"])
    stdio = load("claude/claude_desktop_stdio.json")["mcpServers"]["glasshaus"]
    assert stdio["args"][-3:] == ["glasshaus-mcp", "--transport", "stdio"]
    assert "GLASSHAUS_MCP_TOKEN" in stdio["env"]
    code = load("claude/mcp.json")["mcpServers"]["glasshaus"]
    assert code["type"] == "http" and code["headers"]["Authorization"].startswith("Bearer ")


def test_copilot_studio_connector() -> None:
    spec = yaml.safe_load((DOCS / "copilot-studio/glasshaus-mcp-connector.yaml").read_text())
    assert spec["swagger"] == "2.0"
    assert spec["paths"]["/mcp"]["post"]["x-ms-agentic-protocol"] == "mcp-streamable-1.0"


def test_m365_manifests_reference_real_operations() -> None:
    agent = load("m365/declarativeAgent.json")
    assert agent["version"] == "v1.6" and len(agent["instructions"]) <= 8000
    for action in agent["actions"]:
        assert (DOCS / "m365" / action["file"]).is_file()

    mcp = load("m365/glasshaus-mcp-plugin.json")
    runtime = mcp["runtimes"][0]
    assert mcp["schema_version"] == "v2.4" and runtime["type"] == "RemoteMCPServer"
    assert runtime["spec"]["url"].endswith("/mcp") and runtime["run_for_functions"] == ["*"]

    api = load("m365/glasshaus-api-plugin.json")
    openapi = load("m365/openapi.json")
    assert openapi["openapi"].startswith("3.0")
    operations = {op["operationId"] for ops in openapi["paths"].values() for op in ops.values()}
    assert {f["name"] for f in api["functions"]} == operations
    assert "anyOf" not in json.dumps(openapi)


def test_copilot_openapi_is_current(tmp_path: Path) -> None:
    script = runpy.run_path(str(ROOT / "scripts" / "copilot_openapi.py"))
    out = tmp_path / "openapi.json"
    argv = sys.argv
    sys.argv = ["copilot_openapi.py", str(ROOT / "docs/openapi.json"), str(out)]
    try:
        script["main"]()
    finally:
        sys.argv = argv
    assert out.read_text() == (DOCS / "m365/openapi.json").read_text(), "run `make openapi`"
