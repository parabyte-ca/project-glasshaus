# Feature → API → MCP coverage matrix

Every capability must be reachable through REST, webhooks/events and MCP. This table is updated in each
phase and verified by tests from Phase 6.

| Capability | Service | REST | Event / webhook | MCP tool / resource | Phase |
| --- | --- | --- | --- | --- | --- |
| Server version / health | `system` | `GET /api/v1/version`, `/healthz`, `/readyz` | — | `server_info` | 0 |
