#!/app/.venv/bin/python
import asyncio
import os
import sys

sys.path.insert(0, "/app/src")

from mcp.server.transport_security import TransportSecuritySettings

import server as cognee_mcp_server


cognee_mcp_server.mcp.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False
)

argv = [
    "server.py",
    "--transport",
    "http",
    "--host",
    "0.0.0.0",
    "--port",
    os.getenv("HTTP_PORT", "8000"),
    "--log-level",
    os.getenv("MCP_LOG_LEVEL", "INFO").lower(),
]

api_token = os.getenv("API_TOKEN")
if api_token:
    argv.extend(["--api-token", api_token])

sys.argv = argv

asyncio.run(cognee_mcp_server.main())
