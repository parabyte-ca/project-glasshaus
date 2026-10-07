from mcp import Client

from glasshaus import __version__
from glasshaus.mcp_server.server import server


async def test_server_info_tool() -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
        assert "server_info" in {t.name for t in tools.tools}
        result = await client.call_tool("server_info", {})
        assert result.structured_content is not None
        assert result.structured_content["version"] == __version__
