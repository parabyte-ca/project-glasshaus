# AI assistant

Glasshaus has an optional, built-in AI assistant. It is **off by default** and stays off until both:

1. the server has a provider configured (`GLASSHAUS_AI_PROVIDER`), and
2. an organization owner or admin turns it on in **Admin → AI assistant**, choosing which features
   people may use.

External AI tools (Claude, GitHub Copilot, any MCP client) do not need this: they use the
[MCP server](../README.md#mcp-and-copilot-setup) and their own model.

## What it does

| Feature | Where | What is sent to the model | Result |
| --- | --- | --- | --- |
| Status updates | Project → **Assistant → Status update** | The project's status summary: counts, health, and the keys, titles, statuses, assignee names and dates of completed, in-progress, overdue and due-soon tasks; schedule warnings | A headline, two or three paragraphs, highlights and concerns, with the facts it used |
| Task drafting | Project → **Assistant → Draft tasks** | The brief you type, the project name and description, and up to 100 open task titles (to avoid duplicates) | Proposed tasks (title, description, priority, estimate, tags). **Nothing is created** until you press **Add** |
| Risk flags | Project → **Assistant → Risks** | The status summary plus up to 200 open tasks (key, title, status, priority, assignee name, dates, estimate) | Up to 10 risks with severity, evidence and a next step; task keys not in the data are dropped |
| Ask in plain words | **Ctrl K / ⌘ K** → *Ask: …* | Only your question, today's date, visible project keys and names, and people's names. **No task content** | The filters it chose (shown in plain words) and the matching tasks, found with your permissions |
| Questions about reports (off until an admin ticks it) | **Reports → Ask a question**, a saved report's **Ask about this report**, or **Ctrl K / ⌘ K** → *Ask reports: …* | Step 1: your question, today's date, visible project keys and names, people's names, and the names and descriptions of saved reports you can see. Step 2: the report table (group names such as projects, people and tags, and the numbers, up to 50 rows) and totals. **No task titles or descriptions** | The answer, the report it used (shown as a table or chart so the numbers can be checked), and **Open in the report builder** to adjust or save it |

Everything is read-only. The assistant has no tools and cannot change data; drafts and suggestions are
applied by a person (or an MCP client) through the normal task API. Email addresses and credentials are
never sent.

The same features are available through the REST API (`/api/v1/ai/...`) and MCP (`ai_status`,
`ai_status_report`, `ai_draft_tasks`, `ai_flag_risks`, `ai_search_tasks`, `ai_ask_reports`); see the
[coverage matrix](coverage-matrix.md).

## Providers

| `GLASSHAUS_AI_PROVIDER` | Use | Settings |
| --- | --- | --- |
| `none` (default) | Assistant unavailable | — |
| `anthropic` | Claude through the official Anthropic SDK. Default model `claude-opus-5-5` | `GLASSHAUS_AI_API_KEY` (or `ANTHROPIC_API_KEY`), optional `GLASSHAUS_AI_MODEL`, `GLASSHAUS_AI_EFFORT` (`low`, `medium`, `high`; blank uses the model default), `GLASSHAUS_AI_FALLBACKS` |
| `openai` | Any OpenAI-compatible `/chat/completions` server, e.g. **Ollama**, LM Studio, vLLM, LocalAI (keeps data on your network), or **Azure OpenAI** | `GLASSHAUS_AI_BASE_URL` (e.g. `http://ollama:11434/v1`), `GLASSHAUS_AI_MODEL` (default `llama3.1`), optional `GLASSHAUS_AI_API_KEY`; for Azure also `GLASSHAUS_AI_AUTH_HEADER` and, on classic deployment URLs, `GLASSHAUS_AI_API_VERSION` |
| `fake` | Deterministic sample output for demos and tests | — |

Other settings: `GLASSHAUS_AI_TIMEOUT_SECONDS` (default 120) and `GLASSHAUS_AI_RATE_LIMIT_PER_MINUTE`
(per person, default 10; 0 disables).

Claude requests use structured outputs (a JSON schema per feature), so answers are validated before
they reach you. With `GLASSHAUS_AI_FALLBACKS=true` (default), a request Claude declines is re-run on
Anthropic's recommended fallback model in the same call (beta `server-side-fallback-2026-07-01`); set it
to `false` to turn that off, or if you point `GLASSHAUS_AI_BASE_URL` at a gateway that does not support
it. Local models get the schema in the prompt and as `response_format`; replies that are not valid JSON
are rejected with a clear error.

### Example: Azure OpenAI

Microsoft 365 Copilot has no model API for apps, so for a Microsoft-hosted model use Azure OpenAI
(Azure AI Foundry). Deploy a model (for example `gpt-4.1` or `gpt-5-mini`), then use either endpoint:

```bash
# v1 endpoint (recommended): no api-version needed
GLASSHAUS_AI_PROVIDER=openai
GLASSHAUS_AI_BASE_URL=https://<resource>.openai.azure.com/openai/v1
GLASSHAUS_AI_MODEL=<deployment name>
GLASSHAUS_AI_API_KEY=<key from Keys and Endpoint>
GLASSHAUS_AI_AUTH_HEADER=api-key

# Classic deployment endpoint: add the API version
GLASSHAUS_AI_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment name>
GLASSHAUS_AI_API_VERSION=2024-10-21
```

`GLASSHAUS_AI_AUTH_HEADER=api-key` sends the key in Azure's `api-key` header instead of
`Authorization: Bearer`. Newer reasoning models that refuse `max_tokens` are retried automatically with
`max_completion_tokens`. Data stays in your Azure tenant under Microsoft's Azure OpenAI terms. Microsoft
Entra ID (keyless) sign-in is not supported yet; use a key.

Copilot itself (Microsoft 365 Copilot, Copilot Studio, GitHub Copilot) connects to Glasshaus through the
MCP server instead; see [integrations](integrations/README.md).

### Example: Ollama on the same host

```bash
# docker-compose.override.yml
services:
  ollama:
    image: ollama/ollama:0.12.3
    volumes: [ollama:/root/.ollama]
volumes:
  ollama: {}
```

```bash
docker compose exec ollama ollama pull llama3.1
# .env
GLASSHAUS_AI_PROVIDER=openai
GLASSHAUS_AI_BASE_URL=http://ollama:11434/v1
GLASSHAUS_AI_MODEL=llama3.1
docker compose up -d
```

Smaller local models follow the schema less reliably; if you see "did not match the expected format",
try a larger model.

## Safety and privacy

- **Prompt injection:** project content is wrapped in a `<project_data>` block and the model is told it
  is untrusted data, never instructions. Because the assistant has no tools and its output is only shown
  or proposed, injected text cannot cause actions.
- **Least data:** each feature sends only the fields listed above. Search sends no task content at all.
- **Reports are run by Glasshaus, not the model:** the model only picks a saved report or fills in a
  report definition from fixed lists (unknown projects, people and groupings are dropped); the report
  then runs with the asker's access, exactly as in the report builder. The answer is shown as plain
  text (no links or images) next to the table it was written from.
- **Permissions:** every request runs as the person asking, so the assistant only sees what they can see
  (projects they cannot read return 404).
- **Audit:** each request is recorded as `ai.summaries`, `ai.drafting`, `ai.risks`, `ai.search` or `ai.reports` with the
  outcome, provider, model, token counts and duration — **not** the prompt or the answer.
- **Limits:** per-person rate limit, input caps (brief 4,000 characters, question 500) and output caps
  (15 drafts, 10 risks).
- **Your provider's terms apply** to data sent to it. Use `openai` with a local model to keep everything
  on your own hardware.
