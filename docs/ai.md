# AI features — provider setup

Spoolman NG's AI features (in progress — see the
[LLM integration plan](llm-integration-brainstorm.md)) all talk to a single
**OpenAI-compatible endpoint that you configure**. Spoolman never runs models
itself and ships none: it is only ever an HTTP client of an endpoint you point it
at — an Ollama server on your network, or a cloud provider of your choice.

**Nothing is sent anywhere, and nothing AI-related appears anywhere in the
interface, until you configure an endpoint and enable a feature** under
**Settings → AI**. A stock install is byte-identical to one without any AI code.

## Configuration

Two layers, environment variables winning over the UI:

| Environment variable | Settings → AI field | Purpose |
|---|---|---|
| `SPOOLMAN_AI_BASE_URL` | Base URL | The OpenAI-compatible endpoint, e.g. `http://gaming-pc:11434/v1` |
| `SPOOLMAN_AI_API_KEY` | API key | Bearer token for the endpoint (Ollama and LM Studio need none) |
| `SPOOLMAN_AI_MODEL` | Chat model | Model used for chat/tool features |
| `SPOOLMAN_AI_VISION_MODEL` | Vision model | Model used for image features; falls back to the chat model |

A field set via environment variable is shown locked in the UI. Fields edited in
the UI are stored in the database like other settings — except the API key:

- **The API key is write-only.** It is stored outside the regular settings
  registry, no API endpoint ever returns it, and the UI only shows whether a key
  is set. Replace it by typing a new value; remove it with "Clear stored key".
- Setting or clearing the key (and running connection tests) requires an
  administrator account once user accounts exist. On a default no-auth install,
  anyone with network access to Spoolman can change settings — the same trust
  model as the rest of the API (see "Security & exposure" in the README).

## Providers

Everything that speaks the OpenAI-compatible chat-completions API works. The
preset dropdown fills in the base URL for common choices:

| Provider | Base URL | Key needed |
|---|---|---|
| [Ollama](https://ollama.com/) | `http://<host>:11434/v1` | no |
| LM Studio | `http://<host>:1234/v1` | no |
| [OpenAI](https://platform.openai.com/) | `https://api.openai.com/v1` | yes |
| [Anthropic](https://platform.claude.com/docs/en/api/openai-sdk) | `https://api.anthropic.com/v1` | yes |
| [OpenRouter](https://openrouter.ai/) | `https://openrouter.ai/api/v1` | yes |
| [Requesty](https://www.requesty.ai/) | `https://router.requesty.ai/v1` | yes |
| [Groq](https://groq.com/) | `https://api.groq.com/openai/v1` | yes |
| [Mistral](https://mistral.ai/) | `https://api.mistral.ai/v1` | yes |
| [Gemini](https://ai.google.dev/) | `https://generativelanguage.googleapis.com/v1beta/openai` | yes |
| Anything else | any OpenAI-compatible URL | depends |

Local-first works well: the Spoolman host itself is often a Raspberry Pi, but an
Ollama on any machine on your network (a desktop PC, a NAS) is one URL away.

## The connection test

**Test connection** checks the endpoint and reports per capability:

- **Reachable** — the endpoint answered `/v1/models` (latency and model count shown).
- **Chat / Tool calls / Vision** — reported as *supported*, *not supported*, or
  *not verified*. Ollama endpoints are enriched through Ollama's own API, which
  knows each local model's real capabilities (including "model not pulled").
  Generic endpoints cannot be queried for capabilities, so those honestly report
  *not verified* instead of guessing.

A feature that definitely cannot work with the configured endpoint (for example
Scan-to-Spool with a model that has no vision support) cannot be enabled, with the
reason shown inline.

## Privacy

- With a **local endpoint** (Ollama, LM Studio, llama.cpp, vLLM on your own
  hardware), nothing ever leaves your network.
- With a **cloud provider**, whatever a feature sends (chat messages, photos for
  Scan-to-Spool once it ships) goes to that provider under their terms. You chose
  the endpoint; Spoolman adds no telemetry and no middleman.
- Feature toggles are all **off by default** and independent, so you can, for
  example, enable natural-language search against a local model and leave photo
  features off entirely.

## Related: the built-in MCP server

The **MCP server** section of the same settings tab serves your inventory to AI
assistants (Claude Desktop, claude.ai, Claude Code, ...) straight from Spoolman —
it needs **no AI provider at all**. See [docs/mcp.md](mcp.md).
