# LLM / AI Integration — Brainstorm

> **Status: brainstorm.** Nothing here is committed roadmap. This document collects
> the idea space, prior art, constraints, and a recommended shortlist so we can agree
> on direction before designing UI (ASCII mockups will be appended once ideas are
> agreed) or writing code.

---

## 1. Prior art — what already exists

Worth knowing before building anything, both to avoid duplication and to steal good ideas.

### Spoolman-adjacent

| Project | What it does | Takeaway |
|---|---|---|
| [Disane87/spoolman-mcp](https://github.com/Disane87/spoolman-mcp) | External Node/TypeScript MCP server exposing the full Spoolman REST API (vendors/filaments/spools CRUD, usage logging, settings, custom fields, export, health) to Claude Desktop etc. Config via `SPOOLMAN_URL` + optional bearer token. Already linked from our README; already used by this fork's maintainer. | "Expose Spoolman to an AI assistant" is a **solved problem** — but it needs a separate Node deployment, is version-coupled to upstream's API, and has no vision/no UI. The gap is *built-in* intelligence, not API exposure. |
| [OctoEverywhere MCP server](https://blog.octoeverywhere.com/mcp-server-for-3d-printing/) | MCP for printer status/control/webcam across OctoPrint/Klipper/Bambu ecosystems. | Printer *control* via AI is owned by the printer-facing ecosystem. Spoolman should stay the **inventory brain**, not compete on printer control. |
| [klipper-mcp](https://glama.ai/mcp/servers/@Charleslotto/klipper-mcp) | Community MCP for Moonraker. | Same conclusion. |
| [n8n GPT-4o ↔ OctoPrint workflow](https://n8n.io/workflows/4222-control-your-3d-printer-with-gpt-4o-and-octoprint-api-conversations/) | Conversational printer control via workflow glue. | The DIY crowd wires this themselves; a first-party path is friendlier. |
| Home Assistant + [spoolman-homeassistant](https://github.com/Disane87/spoolman-homeassistant) | Spool entities in HA; HA's Assist pipeline already gives **voice** access to entities via local/cloud LLMs. | A voice story partially exists for HA users today. Worth documenting even if we build nothing. |

### Commercial competitors (validation that vision intake is wanted)

| Product | AI feature |
|---|---|
| [Filametrics](https://www.myfilametrics.com/) | "Add filaments by scanning the box label … let our AI slicer reader do the heavy lifting"; screenshot of slicer → usage auto-logged. |
| [3D Spool Tracker](https://3dspooltracker.com/about) | "Snap a label or box and brand, material, color, and recommended settings populate themselves." |
| [SimplyPrint](https://simplyprint.io/features/filament-management), FilamIQ, Spoolstock | Scanning-centric filament managers (QR/barcode, not LLM). |

**Positioning insight:** closed/cloud products are already selling "photo → inventory".
A **self-hosted, provider-agnostic** version of that is exactly the kind of feature that
fits Spoolman NG's audience and doesn't exist anywhere in the open-source stack.

### Adjacent but out of scope

Print-failure detection from webcams (Obico, PrintWatch, OctoEverywhere Gadget) is a
mature space with dedicated ML products. Spoolman should not point cameras at printers.

---

## 2. Constraints that shape any design

These come from the codebase and deployment reality, not taste:

1. **Host hardware is Pi-class** (README/MASTERPLAN: happily runs on a Pi 3/4 next to
   Klipper). **No on-host inference, ever.** All AI is HTTP calls out — to an Ollama
   box on the LAN, or to a cloud gateway. Spoolman is only ever an HTTP *client*.
2. **No-auth-by-default security model.** Provider API keys are secrets; the DB-backed
   settings API is world-readable on a default install. Keys must be env-vars first
   (`SPOOLMAN_AI_*`), or write-only settings that are never echoed back, masked in UI,
   admin-gated once user accounts exist.
3. **Privacy is a feature.** This community self-hosts *on principle*. Cloud providers
   must be opt-in with a clear "this photo/text leaves your network" affordance.
   Local-first (Ollama) should be the blessed path.
4. **Everything optional.** AI features hidden until configured; zero behavior change
   when off. The fork's promise is drop-in compatibility — an unconfigured install must
   look exactly like today.
5. **CI culture.** ~470 behavioral tests, mutation gates, hermetic e2e. AI endpoints
   need a **mock provider fixture** (recorded responses) so e2e stays hermetic and
   deterministic. A flaky LLM must never flake CI.
6. **i18n.** 30 locales. Chat/summaries should answer in the UI language (cheap: pass
   locale in the system prompt).

### The provider abstraction (shared plumbing for every idea below)

One integration surface covers the whole provider landscape, because everything
relevant speaks the **OpenAI-compatible Chat Completions API**:

| Provider | Base URL | Notes |
|---|---|---|
| [Ollama](https://ollama.com/) | `http://<lan-host>:11434/v1` | Local, free, private. Vision via qwen2.5-vl / llama3.2-vision / moondream. |
| [OpenRouter](https://openrouter.ai/) | `https://openrouter.ai/api/v1` | 400+ models, free tiers, one key. |
| [Requesty](https://www.requesty.ai/) | `https://router.requesty.ai/v1` | Gateway/router, failover, EU residency. |
| LM Studio / llama.cpp / vLLM / LocalAI | `http://<host>:<port>/v1` | All OpenAI-compatible. |
| OpenAI / Groq / Mistral / Gemini (compat) | vendor URLs | Same shape. |

So the config is just: **base URL + API key + model name(s)** — no per-provider SDKs,
no provider enum to maintain. Provider "support" becomes documentation + presets in the
settings UI, not code. Capability probing (vision? tool calls?) at save time tells the
UI which features can light up.

Proposed env/settings surface:

```
SPOOLMAN_AI_BASE_URL      # e.g. http://gaming-pc:11434/v1
SPOOLMAN_AI_API_KEY       # optional (Ollama needs none)
SPOOLMAN_AI_MODEL         # default chat/tool model
SPOOLMAN_AI_VISION_MODEL  # optional; falls back to AI_MODEL if it has vision
```

plus DB settings for non-secrets (feature toggles, temperature, reply language),
and `GET /api/v1/ai/status` reporting `{configured, vision, tools}` so the client
knows what to show.

---

## 3. The idea space

Grouped in clusters; each with value / effort / dependencies. Effort is T-shirt-sized
relative to this codebase (S ≈ days, M ≈ 1–2 weeks, L ≈ multi-week).

### Cluster A — Vision: "Scan-to-Spool" photo intake ⭐

**A1. Label/box photo → prefilled spool.** Take a photo of a spool box or label →
vision model extracts vendor, material, color name, weight, diameter, temps →
**match against SpoolmanDB** (6,957 filaments already synced locally) → user confirms
one of the candidate matches (or raw extraction) → create-filament/spool form arrives
prefilled. The SpoolmanDB match step is the differentiator: instead of trusting OCR,
the LLM output becomes a *search query* against canonical catalog data — clean records,
not typo'd ones. Falls back to raw extraction for unknown brands.
- Hooks that already exist: `filamentImportModal.tsx` (import UX pattern),
  `externaldb.py` (catalog in memory), `scanModal.tsx` + mobile app native camera
  (capture path), filament `picture` support (store the photo on the record).
- Effort: **M**. Value: **highest** — weekly-frequency pain (user story #1–3), matches
  what commercial apps advertise, works one-handed at the shelf via the companion app.

**A2. "Match this color" — photo → inventory search.** Photo of an object/print →
extract dominant color(s) → run the existing color-similarity search
(`colorSimilarityFilter.tsx`) against inventory: "which of my spools matches this?"
Mostly reuses existing similarity math; the LLM is only needed for messy photos
(lighting correction, "the mug, not the table"). Effort: **S–M**. Fun, demo-able.

**A3. Slicer-screenshot usage logging.** Screenshot of the slicer's "filament used"
panel → extract grams/meters → log usage on a chosen spool. Serves Bambu/SD-card users
who lack the Moonraker auto-tracking path (user stories #12, #38). Effort: **S** once
A1's plumbing exists. Filametrics ships exactly this.

**A4. Shelf audit (photo of shelf → diff vs DB).** Count/identify spools on a shelf
photo, diff against the location's expected contents. Ambitious; accuracy will be
mediocre with current open models. Park as **experimental/later**.

**A5. Remaining-% estimate from a side-on spool photo.** Geometrically plausible,
model-hostile (needs calibration per spool type). Park. A cheap 80% version: user
snaps photo, LLM guesses coarse bucket (full/half/low) and suggests opening the
measure dialog. **Later.**

### Cluster B — Chat assistant inside Spoolman

**B1. "Ask Spoolman" chat panel with tool calling.** Server-side agent loop
(`POST /api/v1/ai/chat`, SSE/websocket streaming — `ws.py` infra exists) with a curated
tool set over the internal services: query spools/filaments/stats, log usage, create/
edit entities, archive, locate. Mutations render as **confirm cards** in the chat UI
("Will deduct 23 g from *Prusament Galaxy Black* — Confirm / Cancel") — no silent
writes. Read-only mode maps naturally onto the existing read-only user role.
- Also the natural home for **advisory knowledge** the DB can't answer: "which of my
  filaments survives outdoors?", "drying temp for this PETG?", "what should I reorder?"
  (low-stock page + usage trend as context).
- Effort: **M–L** (the agent loop is S; the polished streaming UI with confirm cards is
  the real work). Value: high and broad — this is the umbrella feature people expect.

**B2. Natural-language search → filters.** A sparkle button in the existing search box:
"matte black under 500 g in shelf B" → translated into the *existing* filter model and
shown as normal, editable filter chips (transparent, correctable, no black box).
Works great with a small local model; almost free once B1's plumbing exists.
Effort: **S**. Possibly the best value-per-effort in this document.

**B3. Insight cards / digest.** Dashboard card phrasing deterministic stats in prose:
"2.3 kg PLA this month (+40% vs June); black PLA runs out ~Aug 10 at this rate."
Optionally a monthly digest. LLM only phrases; math stays in SQL (testable).
Effort: **S–M**. Nice-to-have; low risk.

### Cluster C — Built-in MCP server ⭐

**C1. Mount an MCP endpoint inside Spoolman NG** (streamable-HTTP at `/mcp`, e.g. via
the official Python SDK / FastMCP mounted into the existing FastAPI app). Users point
Claude Desktop / claude.ai / any MCP client at `http://spoolman:7912/mcp` — **zero
extra deployment**, version-locked to the API by construction, auth via the existing
bearer token. Curated tools (inventory query, usage logging, spool create, low-stock
report as a *resource*, "restock advisor" as a *prompt*) rather than blind 1:1 CRUD.
- Relationship to the external `spoolman-mcp`: keep linking it (it works today, covers
  full CRUD); built-in MCP is the "batteries included" path user story #39 asked us to
  version-guarantee.
- **Free bonus: voice + vision for free.** claude.ai mobile voice mode / ChatGPT voice
  talking to Spoolman via MCP is an audio chat we never have to build, on someone
  else's excellent STT/TTS stack.
- **Architecture dogfood:** define the tool layer once — the in-app chat agent (B1)
  calls the *same* tool implementations internally. One tool surface, two consumers.
- Effort: **S–M**. Cheap, differentiating, and de-risks B1 by forcing the tool layer.

### Cluster D — Audio

**D1. Voice input on the chat panel (push-to-talk).** Mic button → recorded clip →
server forwards to a configurable OpenAI-compatible STT endpoint
(`/v1/audio/transcriptions`: whisper.cpp server / Speaches / Groq whisper; *not*
Ollama, which has no STT) → text lands in the same B1 chat. Spoken replies via the
browser's `speechSynthesis` (zero backend, works offline) with server TTS
(Piper/Kokoro via `/v1/audio/speech`) as optional upgrade. Hands-dirty-at-the-printer
is the genuine use case: "log twenty grams on the orange Prusament."
Effort: **S–M** on top of B1. Needs a second endpoint config (STT URL).

**D2. Full-duplex realtime voice chat.** Provider-locked (Realtime APIs), expensive,
websocket-heavy, and D1 + C1 (voice via claude.ai/ChatGPT over MCP) covers ~90% of the
value. **Recommend: not now, revisit when local realtime stacks mature.**

### Cluster E — Quiet intelligence (no chat UI at all)

**E1. Resilient import parsing.** MASTERPLAN flags 3DFP scraping as brittle. Add an
LLM fallback: when the fixed parser fails (or for arbitrary pasted product pages /
Amazon listings / vendor URLs), extract filament fields from the raw HTML/text →
same confirm-before-create flow as A1. Turns "parser broke, generic error" into
degraded-but-working. Effort: **S–M**. Quietly excellent.

**E2. Data-hygiene assistant.** Batch job proposing vendor dedupe ("Prusa" vs "Prusa
Research"), color-name normalization, near-duplicate filaments — always as a
review-and-apply list, never auto-applied. Effort: **M**. Later.

**E3. Translation review aid (dev-side).** Locales are AI-seeded and unproofread
(MASTERPLAN §5); an LLM second-pass review workflow in CI tooling. Dev tooling, not
product. Separate track.

---

## 4. Recommended shortlist & sequencing

The recommendation optimizes for: unique value first, shared plumbing reuse, local-first.

| Phase | What | Why first |
|---|---|---|
| 0 | **Provider foundation** (env/settings, `/api/v1/ai/status`, capability probe, mock-provider test fixture) | Prerequisite for everything; small. |
| 1 | **C1 built-in MCP** + the curated tool layer | Cheapest headline feature; forces the tool design that B1 reuses; instantly useful with Claude; gives voice via claude.ai for free. |
| 2 | **A1 Scan-to-Spool** (+ A3 slicer screenshot as a follow-up) | The flagship. Unique in open source; leverages SpoolmanDB + mobile camera. |
| 3 | **B1 chat panel** + **B2 NL search** | Umbrella UX on top of the phase-1 tool layer. |
| 4 | **D1 voice input** on the chat panel | Thin layer once B1 exists. |
| — | E1 import fallback | Slot in anywhere; independent. |
| Later | A2 color-match, B3 insights, A4/A5, E2 | Park until the above proves out. |

## 5. Open questions (to agree before mockups)

1. **Shortlist agreement** — which of A1 / B1+B2 / C1 / D1 (/ E1) make the cut?
2. **Provider posture** — Ollama-first defaults with cloud presets one click away, or
   fully neutral "paste any base URL"? (Recommendation: neutral core, Ollama-flavored
   docs/presets — matches the self-hosting ethos without excluding OpenRouter/Requesty
   users.)
3. **Chat placement** — floating button + right-side drawer available on every page
   (recommended), a dedicated page, and/or wired into the existing kbar command
   palette?
4. **Key handling** — env-only for v1 (simplest, safest), or also a write-only masked
   setting in the UI for Docker-averse users?

*ASCII UI mockups for the agreed ideas will be appended below as §6.*
