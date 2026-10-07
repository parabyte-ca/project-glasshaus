"""Run the MCP server: ``python -m glasshaus.mcp_server [--transport http|stdio]``."""

import argparse

from glasshaus.logs import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="glasshaus-mcp")
    parser.add_argument("--transport", choices=["http", "stdio"], default="http")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.transport == "stdio":
        import sys

        configure_logging(stream=sys.stderr)  # stdout is the JSON-RPC channel
        from glasshaus.mcp_server.server import server

        server.run("stdio")
        return

    import uvicorn

    configure_logging()
    from glasshaus.mcp_server.server import create_http_app

    uvicorn.run(create_http_app(), host=args.host, port=args.port, log_config=None, proxy_headers=True)


if __name__ == "__main__":
    main()
