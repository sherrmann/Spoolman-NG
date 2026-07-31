# AI features — provider setup

Spoolman NG's AI features all talk to a single
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
| `SPOOLMAN_AI_STT_BASE_URL` | STT base URL | Speech-to-text endpoint for voice input, e.g. `http://whisper:8000/v1` |
| `SPOOLMAN_AI_STT_API_KEY` | STT API key | Bearer token for the transcription endpoint (local whisper needs none) |
| `SPOOLMAN_AI_STT_MODEL` | STT model | Transcription model, e.g. `whisper-1` |

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

## Running a model locally

You don't have to bring your own endpoint — Spoolman can set up a local
[Ollama](https://ollama.com/) runtime for you so everything stays on your own
hardware. Spoolman **manages models, never the runtime**: once Ollama is running,
the model shortlist and downloads live in **Settings → AI**.

Local AI wants a 64-bit OS (amd64 or arm64) and ideally 8 GB+ RAM or a GPU. It is
unavailable on 32-bit ARM (armv7), where Ollama ships no build — point
`SPOOLMAN_AI_BASE_URL` at an Ollama on another machine instead.

- **Docker Compose.** The [setup wizard](../guide) has a *Local AI assistant*
  option that adds an `ollama` service to your generated `docker-compose.yml`, a
  named volume for the model weights, and
  `SPOOLMAN_AI_BASE_URL=http://ollama:11434/v1` on the Spoolman service. Bring the
  stack up and the endpoint is already wired.
- **Native install.** Run the installer with `--with-ai`
  (`bash scripts/install.sh --with-ai`): it installs the Ollama runtime, enables
  its service, and sets `SPOOLMAN_AI_BASE_URL` in your `.env`. The
  [KIAUH extension](../integrations/kiauh) offers the same as a *Also set up local
  AI (Ollama)?* prompt during install. No models are downloaded by the installer.

**Pulling a model.** However Ollama got there, open **Settings → AI**. When the
endpoint is an Ollama server, an **Ollama models** panel lists a curated shortlist
(small and standard chat models plus vision models) with installed status and
download size, and pulls the one you pick with a live progress bar — no shell
required.

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

## Scan-to-Spool

Turn on **Scan-to-Spool** under Settings → AI (it needs a vision-capable model —
`qwen2.5-vl`, `llama3.2-vision`, `gpt-4o-mini`, Claude, ... — set as the vision or
chat model). The scan dialog on the Spools page then gains a **Photo** tab next to
QR and barcode scanning.

The flow:

1. **Photograph the label** (or the box). On phones this opens the camera
   directly. The photo is downscaled in your browser before upload.
2. **The model reads the label** and returns the structured fields it could see:
   vendor, name, material, weight, diameter, temperatures, lot number, article
   number — never guessing at what it can't.
3. **Spoolman matches, your library first.** If the filament already exists in
   your library, the top suggestion just adds a spool to it. Otherwise close
   matches from the [SpoolmanDB](https://github.com/Donkie/SpoolmanDB) catalog are
   offered — picking one creates the filament and the spool in a single save. The
   raw extracted values are always available as a fallback that prefills a blank
   filament form.
4. **Review and continue.** Nothing is created until you land on the normal
   create form, prefilled, with every value still editable.

The photo is processed in memory and discarded after extraction — it is not
saved on the server or in the browser. The lot number, if the label has one,
is carried onto the spool so the physical label stays scannable later.

Extraction and matching are separate API steps (`/ai/spool-intake/extract` and
`/ai/spool-intake/match`): the match stage accepts extraction JSON with no image
attached, so a future mobile app that runs a vision model on the device itself can
use the same matching without any photo leaving the phone.

## Chat assistant

Turn on **Chat assistant** under Settings → AI. A second floating button (above the
scan button) then opens a chat drawer on every page. Ask about your inventory in plain
language:

- *"How much black PETG do I have left?"* — answers with per-spool numbers and a total,
  plus a **View in Spools list** link that applies the equivalent filter.
- *"What should I reorder?"* / *"Which of my filaments survive outdoors?"* — advisory
  answers from your low-stock, reserve, and on-order data combined with general
  3D-printing knowledge.

The assistant reads and writes your data through a small **curated tool layer** — the same
set of read/write actions a person has in the web UI, nothing more. It can reach spools and
filaments, usage statistics and spend, orders and their arrival, locations and vendors, and
the SpoolmanDB catalog. It never runs raw queries.

**Changes are never silent.** When the assistant wants to create, update, consume, or
delete something, it renders a **confirm-card** showing the before/after values with
**Confirm** / **Cancel** buttons — nothing happens until you confirm. After a change runs,
a one-click **Undo** restores the previous state — with three exceptions. Deletes cannot be
undone in one click and require an explicit request; deleting a filament also deletes its
spools and their usage history, and the confirm-card states exactly how many. Marking an
order arrived also cannot be undone in one click: it can create a spool per unit in the same
step, and because that splits order lines there is no clean single call that reverses it, so
its confirm-card spells out exactly what will be created before you confirm. Undoing a filament
**creation** is also refused, rather than silently deleting, if you've added spools to it since —
you'll be told how many, and can delete the filament explicitly (with its own confirm-card) if
that is really what you want. A **read-only** account can use the assistant to ask questions but
is offered no write actions at all.

When updating a filament or a spool, an omitted field is left unchanged and an explicit
`null` clears it — except a filament's density and diameter, which can never be null and
are rejected with an error rather than cleared, since a spool's weight math depends on
both. Everywhere else, "clear the comment" and a request that just doesn't mention the
comment behave differently, as they should, and undoing an edit can restore a field that
was previously empty. The assistant never invents a filament's density or diameter in the
first place — it looks them up in the SpoolmanDB catalog or asks you.

The assistant replies in the interface language and never uses emoji. Each turn sends the
current conversation and a short note of which page you are on to the configured endpoint;
as always, with a local endpoint nothing leaves your network.

## Natural-language search

Turn on **Natural-language search** under Settings → AI. An **AI** button then appears
next to the search box on the Spools page. Type a request like *"matte black PETG in
shelf B"* and it is translated into the **normal, editable filter chips** — material,
vendor, location, lot number, colour, and sort — that you could have set by hand. Nothing
is a black box: the filters are shown and fully correctable, and you can clear or tweak
any of them.

The translation is **grounded on your actual data**: the model is given the real list of
materials, vendors, and locations in your database and may only choose from them. Anything
it can't map to a real value is dropped rather than invented, and if a request can't be
translated at all it falls back to the ordinary free-text search — the AI button never
blocks the normal path. It works well with a small local model.

## Voice input

For the genuine hands-dirty-at-the-printer case — *"log twenty grams on the orange
Prusament"* — the chat assistant can take voice. It needs a **separate speech-to-text
endpoint**: chat providers like Ollama have no transcription, so voice points at its own
OpenAI-compatible `/v1/audio/transcriptions` server (a
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) server,
[Speaches](https://github.com/speaches-ai/speaches), Groq whisper, ...). Set its **STT base
URL**, **model**, and (if needed) **API key** under Settings → AI, then enable **Voice
input** — the toggle stays greyed until a transcription endpoint is configured.

A **mic button** then appears in the chat input. **Hold to talk**, release to transcribe;
drag off the button to cancel. By default the recognised text lands **editable in the input
box** so you can fix it before sending — speech-to-text mangles vendor names ("Sunlu" →
"sun blue"), so review is the default. Tick **Send voice transcripts automatically** under
Settings → AI to skip the review step. Sent transcripts run through the normal chat flow,
confirm-cards and all — a spoken "archive spool 12" still asks you to confirm.

A **Speak replies** switch in the drawer header reads answers aloud using your browser's
built-in speech synthesis (no server needed). The audio clip is sent only to your
configured STT endpoint and is never stored by Spoolman.

## MCP server

Turn on **MCP server** under Settings → AI. Spoolman then serves a
[Model Context Protocol](https://modelcontextprotocol.io/) endpoint over streamable HTTP at
**`/mcp`**, so any MCP client — Claude Desktop, claude.ai, ChatGPT — can query and update
your inventory directly. Unlike the other features it needs **no LLM provider of its own**;
the toggle is all it requires (the *client* brings the model), and the endpoint answers 404
until you enable it.

Settings → AI shows a ready-to-paste config once it's on:

```json
{
  "mcpServers": {
    "spoolman": {
      "url": "https://your-spoolman-host/mcp"
    }
  }
}
```

**Auth reuses your API token.** On a token-less install anyone with network access can
connect (the same trust model as the rest of the API). When `SPOOLMAN_API_TOKEN` is set — or
user accounts exist — the client must send it as a bearer token; add it under `headers`:

```json
"spoolman": {
  "url": "https://your-spoolman-host/mcp",
  "headers": { "Authorization": "Bearer <your token>" }
}
```

A **read-only** account (or read-only user token) is offered the query tools only — no
mutating tools appear at all.

What the client gets:

- **Tools** — the same curated set the in-app chat assistant uses (one tool surface, two
  consumers): search spools, list filaments with low-stock/on-order status, usage statistics
  and spend, orders, locations, vendors, and SpoolmanDB catalog lookup — and, for a writer,
  create a spool, log usage, edit a spool, create or edit a filament, record an order, mark
  an order arrived, and create a location or vendor. It is a curated layer, not raw database
  access; deletes are not exposed over MCP. Marking an order arrived has no undo and no
  confirm-card here, so it is the one write flagged `destructive` in its tool annotation —
  a client can use that to prompt its own user before running it.
- A **low-stock resource** the client can read for the current reorder picture.
- A **restock-advisor prompt** that turns that data into "what should I reorder?".

This is the batteries-included, version-guaranteed path: the tools always match the running
Spoolman. For full CRUD you can still point the external
[Disane87/spoolman-mcp](https://github.com/Disane87/spoolman-mcp) at your instance — the two
coexist.

Voice and vision come for free here: talking to Spoolman through claude.ai or ChatGPT voice
mode is an audio interface Spoolman never has to build.

## Tool-selection eval (maintainers)

Growing the tool surface trades reach for tool-selection accuracy on small local models, and
Spoolman's whole premise is "point it at your own Ollama". `poe ai-eval` turns that trade into
a number: it sends a fixed set of fixture prompts through the real tool schemas to a live
OpenAI-compatible endpoint and checks which tool the model reached for, then reports overall
and per-tool accuracy plus a confusion table.

```bash
SPOOLMAN_AI_BASE_URL=http://localhost:11434/v1 SPOOLMAN_AI_MODEL=<model> uv run poe ai-eval
```

It needs a live endpoint, so it is **not part of CI** — run it before a release and whenever
the tool set changes. The harness's own system prompt is built from the same
`_system_prompt` the in-app chat agent actually sends (writer posture, English locale, no page
context), so the eval measures the configuration Spoolman ships, not a thinner stand-in.

Measured across 2 runs against a local Ollama 7.6B tool-tuned model
(`hhao/qwen2.5-coder-tools`) on the same 53 fixture prompts: **47-48/53 (89-91%)** tool
selection, **44-46/53 (83-87%)** with correct arguments too, run to run. Treat that range as one
small local model's variance on one machine, not a guarantee for whatever endpoint you point
Spoolman at, and expect the exact numbers to drift a little between any two runs — a single
best-of-N figure understates that. The dominant failure mode across both runs is the model
declining to call any tool at all, not calling the wrong one.

## Privacy

- With a **local endpoint** (Ollama, LM Studio, llama.cpp, vLLM on your own
  hardware), nothing ever leaves your network.
- With a **cloud provider**, whatever a feature sends (chat messages, photos for
  Scan-to-Spool) goes to that provider under their terms. You chose the endpoint;
  Spoolman adds no telemetry and no middleman.
- Feature toggles are all **off by default** and independent, so you can, for
  example, enable natural-language search against a local model and leave photo
  features off entirely.
