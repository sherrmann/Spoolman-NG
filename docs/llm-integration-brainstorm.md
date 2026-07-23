# LLM / AI Integration — Brainstorm

> **Status: agreed and on the tracker — no code yet.** This document collects the
> idea space, prior art, constraints, and the agreed direction. The shortlist and UI
> direction were agreed on 2026-07-23 (see §5), ASCII mockups live in §6, and the
> phases are filed as issues #359–#364 (see the table in §4). The competitive
> teardown of Filametrics / 3D Spool Tracker is tracked in #358.

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

1. **Host hardware ranges from Pi 3 to homelab x86** (README/MASTERPLAN: happily runs
   on a Pi 3/4 next to Klipper; Unraid/TrueNAS/BigBear integrations show a real
   NAS/homelab cohort). **No inference inside the Spoolman process or image, ever** —
   Spoolman is only ever an HTTP *client*. A co-located model server (sidecar
   container, native service) on capable hosts is fair game and can even be
   provisioned by our tooling — see Cluster F — but the runtime is never ours.
2. **No-auth-by-default security model.** Provider API keys are secrets; the DB-backed
   settings API is world-readable on a default install. Keys must be env-vars first
   (`SPOOLMAN_AI_*`), or write-only settings that are never echoed back, masked in UI,
   admin-gated once user accounts exist.
3. **Privacy is a feature — stated in docs, not in the UI.** This community
   self-hosts *on principle*, so cloud providers are strictly opt-in and the docs say
   plainly which features send what to the configured endpoint. The UI itself carries
   no privacy copy: no "stays on your LAN" badges or inline notes — the user
   configured the endpoint and knows where it points.
4. **Invisible unless enabled.** Zero behavior *and zero UI* change when
   unconfigured: no chat button, no Photo tab in the scan modal, no AI search
   affordance, no mic — none of it renders until the corresponding feature is
   switched on in Settings. The AI settings tab is the single discovery point. The
   fork's promise is drop-in compatibility — a stock install must look exactly like
   today.
5. **No emoji in the product UI.** Buttons, labels, hints, and AI-generated
   responses use plain text and the existing icon set — no sparkles, no emoji
   flourishes (the system prompt instructs the model accordingly).
6. **CI culture.** ~470 behavioral tests, mutation gates, hermetic e2e. AI endpoints
   need a **mock provider fixture** (recorded responses) so e2e stays hermetic and
   deterministic. A flaky LLM must never flake CI.
7. **i18n.** 30 locales. Chat/summaries should answer in the UI language (cheap: pass
   locale in the system prompt).

### The provider abstraction (shared plumbing for every idea below)

One integration surface covers the whole provider landscape, because everything
relevant speaks the **OpenAI-compatible Chat Completions API**:

| Provider | Base URL | Notes |
|---|---|---|
| [Ollama](https://ollama.com/) | `http://<lan-host>:11434/v1` | Local, free, private. Vision via qwen2.5-vl / llama3.2-vision / moondream. |
| LM Studio / llama.cpp / vLLM / LocalAI | `http://<host>:<port>/v1` | Local servers, all OpenAI-compatible. |
| [OpenAI](https://platform.openai.com/) | `https://api.openai.com/v1` | First-party API. |
| [Anthropic](https://platform.claude.com/docs/en/api/openai-sdk) | `https://api.anthropic.com/v1/` | Official OpenAI-SDK compatibility layer over the Claude API — chat, streaming, tool calls, and `image_url` vision input all work through it. Anthropic positions it as an evaluation layer (the native API has more features: prompt caching, strict schemas), but it covers everything Spoolman's chat-completions client needs. |
| [OpenRouter](https://openrouter.ai/) | `https://openrouter.ai/api/v1` | 400+ models behind one key, free tiers. |
| [Requesty](https://www.requesty.ai/) | `https://router.requesty.ai/v1` | Gateway/router, failover, EU data residency. |
| [Groq](https://groq.com/) | `https://api.groq.com/openai/v1` | Fast inference; also serves OpenAI-compatible Whisper STT (relevant for D1). |
| Mistral / Gemini / xAI / Azure OpenAI / … | vendor compat URLs | e.g. Gemini at `…/v1beta/openai/`; the pattern generalizes. |

Presets are **data, not code** — supporting another provider means adding a row
(name, base URL, docs link) to the preset list, never a new client implementation.

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

### Cluster A — Vision: "Scan-to-Spool" photo intake

**A1. Label/box photo → prefilled spool.** Take a photo of a spool box or label →
vision model extracts vendor, material, color name, weight, diameter, temps → match
in two stages: first against **the user's own filament library** (they may already
have this filament defined — then the flow simply adds a spool to it, avoiding
duplicate filament records), then against **SpoolmanDB** (6,957 filaments already
synced locally) for canonical catalog data → user confirms a candidate (or raw
extraction) → the normal create form arrives prefilled. The match step is the
differentiator: instead of trusting OCR, the LLM output becomes a *search query*
against known-good data. Falls back to raw extraction for unknown brands. **The
photo is ephemeral** — held in memory for extraction and the review screen, never
persisted server-side (users will typically photograph the label; there is no
reason to keep the image).
- Hooks that already exist: `filamentImportModal.tsx` (import UX pattern),
  `externaldb.py` (catalog in memory), `scanModal.tsx` + mobile app native camera
  (capture path).
- Design note: keep extraction and matching as separate steps with a JSON contract
  between them. Matching is plain fuzzy search (no LLM), so the extraction step can
  later move **on-device** in the companion app (Cluster F5) and reuse the same
  match endpoint and review flow — Scan-to-Spool with no configured endpoint at all.
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

### Cluster C — Built-in MCP server

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

### Cluster F — Zero-config local models: provision, don't embed *(agreed 2026-07-23 — F1–F3 tracked in #364; F4/F5 later-bucket)*

The biggest onboarding cliff for every idea above is "step one: already have an LLM
endpoint." The fix is **not** bundling inference into Spoolman (image size, the
armv7/arm64/amd64 matrix, GPU drivers — and a Pi 3 will never run a vision model
regardless of packaging). It is automating two things around the existing
HTTP-client design: standing the endpoint up *next to* Spoolman, and putting the
right models *on* it.

**F1. Install-wizard AI sidecar (Docker).** The interactive setup wizard already
generates compose files with DB sidecars, and CI boots wizard-generated composes
(#341/#356). Add an "AI features?" step: asks arch/RAM/GPU → emits an `ollama`
service block (arm64/amd64 only), volume, and `SPOOLMAN_AI_BASE_URL=http://ollama:11434/v1`,
plus honest expectation copy (what runs on this hardware, disk needs). The same
pattern later emits a whisper-compatible STT sidecar (Speaches) for D1. Effort: M.

**F2. Managed model pull from the settings UI.** Ollama exposes a streaming pull API
(`POST /api/pull`). Once *any* Ollama is reachable — sidecar or gaming PC — Spoolman
can list installed models, compare against a maintained recommendation table (per
feature × hardware tier; data, not code, like the provider presets) and offer
"[ Pull recommended models ]" with progress. The genuinely automatic piece that is
safe to own: we manage models, never the runtime. Effort: S–M on top of #359.

**F3. Native-install option.** `scripts/install.sh --with-ai` and a KIAUH extension
menu entry: run Ollama's installer, enable the systemd unit, preconfigure the env.
Hard-gated on arm64/x86_64 plus a RAM threshold; refuses on armv7. Effort: S.

**F4. In-browser models (WebLLM / transformers.js on WebGPU) — later/experimental.**
0.5–2B models can run client-side; plausibly covers **B2 NL search only** (tiny
model, structured output) as a zero-endpoint default. Costs: ~0.5–1 GB first-run
download, WebGPU device variance, and a second inference path to test. Park until
B2 ships and demand shows. If picked up, note that `.litertlm` models also run on
Web via the Google AI Edge stack — a second candidate runtime besides WebLLM. (For
phones, F5's native on-device path supersedes the in-browser one.)

**F5. On-device models in the companion app (Gemma 3n via LiteRT-LM) — upgraded
from "far later" to a credible path (2026-07-23).** The 2025/26 on-device wave
changed this picture: Google's AI Edge Gallery runs Gemma 3n-class multimodal
models (text + image + audio input) comfortably on budget Android hardware —
confirmed first-hand on this project's maintainer's phone — and is on Google Play
and, since April 2026, on iOS. The embeddable runtime is the LiteRT-LM Kotlin API
(MediaPipe LLM Inference is maintenance-only); `.litertlm` builds of Gemma 3n
E2B/E4B are downloaded on first use (~3–4.5 GB — never shipped in the APK).

The architecturally sweet variant: **on-device extraction + server-side non-LLM
matching**. The A1 match pipeline (own library → SpoolmanDB → raw) is fuzzy
search, not inference — so a phone that extracts the label locally and POSTs
structured JSON to the match endpoint delivers the flagship feature with *zero
configured endpoint anywhere*. The same models' audio input could eventually cover
on-device voice capture too.

What gates this is no longer the models but the companion app: it is a WebView POC
today, and embedding LiteRT-LM is real native work (P1+ of its roadmap). Once the
app grows native surface, this becomes the strongest zero-config story in this
document. iOS parity: LiteRT on iOS, or Apple's Foundation Models framework for
text-only tasks.

**Non-goals, explicitly:** Spoolman never spawns or supervises containers
(mounting `docker.sock` into a default-unauthenticated app is a host-takeover
primitive one LAN port away — a non-starter), and never ships model weights or an
inference engine in its own image. "Managed" ends at generating config and driving
a reachable Ollama's own API.

**Hardware honesty** (ships as wizard/docs copy, and gates F1/F3):

| Host | Text (NL search, chat) | Vision (Scan-to-Spool) | Verdict |
|---|---|---|---|
| Pi 3 / armv7 | no | no | Cloud gateway or another LAN box only |
| Pi 4/5, 4–8 GB (arm64) | small models (~0.5–3B), seconds per answer | marginal at best — benchmark before promising anything | Text-only tier |
| x86 NAS / homelab (Unraid, TrueNAS) | yes | yes (3–7B VLMs; GPU nice, not required) | Sweet spot. Unraid users may already run Ollama from Community Apps — then F1 reduces to a docs paragraph |
| Gaming PC elsewhere on LAN | yes | yes | Today's blessed path (plain #359 preset) |
| Budget–midrange phone (companion app, F5) | yes (Gemma 3n E2B class) | yes — comfortable on budget Android per first-hand testing; scan-and-review latency is fine | Gated on companion-app native work, not on models |

---

## 4. Recommended shortlist & sequencing

The recommendation optimizes for: unique value first, shared plumbing reuse, local-first.

| Phase | What | Issue | Why first |
|---|---|---|---|
| 0 | **Provider foundation** (env/settings, `/api/v1/ai/status`, capability probe, mock-provider test fixture) | [#359](https://github.com/sherrmann/Spoolman-NG/issues/359) | Prerequisite for everything; small. |
| 1 | **C1 built-in MCP** + the curated tool layer | [#360](https://github.com/sherrmann/Spoolman-NG/issues/360) | Cheapest headline feature; forces the tool design that B1 reuses; instantly useful with Claude; gives voice via claude.ai for free. Needs no LLM provider at all. |
| 2 | **A1 Scan-to-Spool** (+ A3 slicer screenshot as a follow-up issue) | [#361](https://github.com/sherrmann/Spoolman-NG/issues/361) | The flagship. Unique in open source; leverages SpoolmanDB + mobile camera. |
| 3 | **B1 chat panel** + **B2 NL search** | [#362](https://github.com/sherrmann/Spoolman-NG/issues/362) | Umbrella UX on top of the phase-1 tool layer. |
| 4 | **D1 voice input** on the chat panel | [#363](https://github.com/sherrmann/Spoolman-NG/issues/363) | Thin layer once B1 exists. |
| — | **F1–F3 assisted local setup** (wizard sidecar, managed model pull, native option) | [#364](https://github.com/sherrmann/Spoolman-NG/issues/364) | Independent of the feature phases; pairs naturally with phase 0. |
| — | E1 import fallback | file when picked up | Slot in anywhere; independent. |
| Later | A2 color-match, B3 insights, A4/A5, E2 | — | Park until the above proves out. |

Competitive teardown of Filametrics / 3D Spool Tracker:
[#358](https://github.com/sherrmann/Spoolman-NG/issues/358) (analysis posted; hands-on
pass with their free tiers still open, and worth doing before finalizing the A1
review screen).

## 5. Decisions (agreed 2026-07-23)

1. **Shortlist** — all four move to mockups: **A1** Scan-to-Spool, **B1+B2** chat +
   NL search, **C1** built-in MCP + AI settings, **D1** voice input.
2. **Provider posture** — **neutral core + presets**: the engine is "any
   OpenAI-compatible base URL"; the settings UI offers one-click presets (Ollama,
   OpenRouter, Requesty, LM Studio); docs lead with Ollama.
3. **Chat placement** — **floating action button + right-side drawer** on every page
   (keeps page context), stacked with the existing scan FloatButton.
4. **Key handling** — env vars are authoritative (`SPOOLMAN_AI_*`); the UI offers a
   write-only, masked field that is never echoed back by the API.

### Round 2 refinements (2026-07-23)

5. **Provider presets expanded** — OpenAI and Anthropic join the presets (Anthropic
   via its official OpenAI-SDK compatibility endpoint `https://api.anthropic.com/v1/`),
   alongside Groq, Mistral, Gemini, xAI, and any other OpenAI-compatible URL.
   Presets are data, not code.
6. **No emoji in the product UI** — buttons, labels, hints, and model responses use
   plain text and the existing icon set.
7. **AI is invisible unless enabled** — zero affordances anywhere until a feature is
   switched on; the Settings tab is the only discovery point.
8. **No privacy copy in the UI** — "stays on your LAN"-style inline notes dropped;
   the privacy posture lives in the docs.
9. **Scan-to-Spool photos are ephemeral** — analyzed in memory, shown once on the
   review screen, never persisted (users typically photograph the label).
10. **Match order: own library first** — extraction matches the user's existing
    filaments before SpoolmanDB, so a known filament gains a spool instead of a
    duplicate filament record.

### Round 3 refinements (2026-07-23)

11. **Cluster F agreed — provision, don't embed.** F1 (wizard AI sidecar) + F2
    (managed model pull via Ollama's own API) + F3 (native `--with-ai`) are tracked
    in [#364](https://github.com/sherrmann/Spoolman-NG/issues/364). Spoolman never
    spawns containers and never bundles inference; "managed" ends at generated
    config and driving a reachable Ollama's API.
12. **F5 acknowledged as the eventual zero-config flagship path** — Gemma 3n-class
    on-device models via LiteRT-LM in the companion app, maintainer-confirmed
    comfortable on budget Android. Gated on the companion app growing native
    surface, not on models. The A1 extraction/matching JSON contract (mirrored
    into #361) keeps this path open; F4 (in-browser) stays experimental/later.

---

## 6. ASCII UI mockups

Visual language: these reuse the existing chrome — Ant Design + Refine layout, the
sidebar (Home / Spools / Filaments / Vendors / Locations / Low stock / Orders /
Settings / Help), the global scan `FloatButton`, the `Segmented` control in the scan
modal, and ordinary filter chips. No emoji anywhere. Per the invisibility principle,
every affordance below (chat button, AI search button, Photo tab, mic) renders only
when its feature is enabled in Settings — a stock install shows none of it.

### 6.1 Settings → AI (C1 foundation — provider config, capabilities, features, MCP)

A new tab next to General / Extra fields / Import & Export / Printers / Users:

```text
┌─ Settings ─────────────────────────────────────────────────────────────────┐
│  General │ Extra fields │ Import & Export │ Printers │ Users │ AI          │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  PROVIDER                                                                  │
│  Preset  [ Ollama              v ]    Ollama · LM Studio · OpenAI ·        │
│                                       Anthropic · OpenRouter · Requesty ·  │
│                                       Groq · Mistral · Gemini · Custom     │
│  Base URL      [ http://gaming-pc:11434/v1                    ]            │
│  API key       [ ************  (write-only, never shown)      ]  [ clear ] │
│                Env vars win when set: SPOOLMAN_AI_BASE_URL / _API_KEY      │
│  Chat model    [ qwen3:8b            v ]   fetched live from /v1/models    │
│  Vision model  [ qwen2.5-vl:7b       v ]   empty = use chat model          │
│                                                                            │
│  [ Test connection ]                                                       │
│  ┌────────────────────────────────────────────────────────────────┐        │
│  │ ✓ Reachable (142 ms)    ✓ Chat    ✓ Tool calls    ✓ Vision     │        │
│  │ ✗ Transcription — add an STT endpoint below to enable Voice    │        │
│  └────────────────────────────────────────────────────────────────┘        │
│                                                                            │
│  FEATURES   (all off by default; nothing appears in the UI until enabled)  │
│  [x] Chat assistant ("Ask Spoolman")                                       │
│  [x] Scan-to-Spool photo intake                                            │
│  [x] Natural-language search                                               │
│  [ ] Voice input (push-to-talk)                                            │
│      STT endpoint [ http://gaming-pc:8971/v1  (whisper-compatible) ]       │
│                                                                            │
│  MCP SERVER — use Spoolman from Claude and other assistants                │
│  [x] Enable MCP endpoint at /mcp   (streamable HTTP)                       │
│      Auth reuses SPOOLMAN_API_TOKEN when set                               │
│      Connector URL  [ http://spoolman.local:7912/mcp ]  [ Copy config ]    │
└────────────────────────────────────────────────────────────────────────────┘
```

- Picking a preset fills the base URL (and a docs link for getting a key/model);
  the Anthropic preset points at `https://api.anthropic.com/v1/`, its official
  OpenAI-compatibility endpoint. Custom accepts any OpenAI-compatible URL.
- Capability probe drives feature availability: no vision model → Scan-to-Spool row is
  greyed with the reason inline (same pattern as the planned Web-NFC "why unavailable"
  work).
- "Copy config" copies a ready Claude Desktop `mcpServers` JSON block, e.g.:

```json
{ "mcpServers": { "spoolman": {
    "type": "http",
    "url": "http://spoolman.local:7912/mcp",
    "headers": { "Authorization": "Bearer <token-if-set>" } } } }
```

### 6.2 A1 Scan-to-Spool — capture → review/match → prefilled form

**Step 1 — capture.** The existing global scan modal gains a third `Segmented` tab
(camera on phone via companion app, file upload on desktop). The tab exists only
while Scan-to-Spool is enabled:

```text
            ┌─ Scan ──────────────────────────────┐
            │    ( QR )   ( NFC )   ( * Photo )   │
            │  ┌───────────────────────────────┐  │
            │  │                               │  │
            │  │       [ camera preview ]      │  │
            │  │    frame the label or box     │  │
            │  │                               │  │
            │  └───────────────────────────────┘  │
            │                                     │
            │       ( Shutter )     [ Upload ]    │
            └─────────────────────────────────────┘
```

**Step 2 — review & match.** Vision extraction on the left; the extraction is used
as a *query*, matched first against the user's own filament library, then against
the locally-synced SpoolmanDB catalog — known data beats OCR. The photo is held in
memory only and discarded after this step:

```text
┌─ Scan-to-Spool — review ───────────────────────────────────────────────────┐
│  ┌──────────┐  EXTRACTED FROM PHOTO      MATCHES (best first)              │
│  │  photo   │  vendor    Prusa Polymers                                    │
│  │ preview  │  material  PETG            your filaments                    │
│  │(not kept)│  color     Prusa Orange    (*) #7 Prusament PETG             │
│  └──────────┘  weight    1000 g              Prusa Orange — in library;    │
│  confidence:   diameter  1.75 mm             just adds a spool to it       │
│  high          temps     240 / 85 °C                                       │
│                lot nr    A123-04         SpoolmanDB catalog                │
│                                          ( ) Prusament PETG Orange · 1 kg │
│                                              creates filament + spool     │
│                                          ( ) use raw extraction as typed  │
│                                                                            │
│  Selected: add 1 spool to existing filament #7 · lot A123-04               │
│  Photo is discarded after this step; fields stay editable on the next      │
│  screen.                                    [ Cancel ]   [ Continue ]      │
└────────────────────────────────────────────────────────────────────────────┘
```

**Step 3 — handoff to the normal create form**, nothing new to learn (`*` marks the
prefilled fields, rendered as a subtle highlight in the real UI):

```text
┌─ New spool ────────────────────────────────────────────────────────────────┐
│  7 fields prefilled from photo — review the highlighted ones               │
│                                                                            │
│  Filament   [ Prusament PETG Prusa Orange   v ]*    Price  [ 29.99 ]*      │
│  Weight     [ 1000 g ]*   Lot nr [ A123-04 ]*   Location [ Shelf B   v ]   │
│  ...                                                                       │
│                                              [ Cancel ]  [ Create spool ]  │
└────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 B1 "Ask Spoolman" — FAB + right drawer with confirm-cards

A second FloatButton stacks above the existing scan one (both only when their
feature is on); the drawer overlays any page and receives that page as context:

```text
┌──────────┬───────────────────────────────────┬─────────────────────────────┐
│ Spoolman │  Spools                           │ Ask Spoolman  [clear] [ x ] │
│──────────│  [ search…     ][ AI ] [ + Add ]  │ qwen3:8b · speak replies:off│
│  Home    │ ┌──┬──────────┬──────┬─────────┐  ├─────────────────────────────┤
│▸ Spools  │ │id│ filament │ left │ location│  │ context: Spools list        │
│  Filam.  │ ├──┼──────────┼──────┼─────────┤  │                             │
│  Vendors │ │12│ PETG ora…│ 622 g│ Shelf B │  │ you: how much black PETG    │
│  Locat.  │ │17│ PLA blac…│ 143 g│ Shelf A │  │      do I have left?        │
│  Low st. │ │23│ ASA whit…│ 891 g│ Drybox 1│  │                             │
│  Orders  │ └──┴──────────┴──────┴─────────┘  │ ai:  3 spools, 1 462 g:     │
│  Settings│                                   │      · #17 Prusament  143 g │
│  Help    │                                   │      · #31 Sunlu      498 g │
│          │                                   │      · #44 eSun       821 g │
│          │                                   │      #17 is under your low- │
│          │                                   │      stock threshold.       │
│          │                     ( AI )  new   │      [ show in list ]       │
│          │                     (scan)  as-is │                             │
│          │                                   │ [ mic ] [ type a message… ] │
└──────────┴───────────────────────────────────┴─────────────────────────────┘
```

Writes never happen silently — tool calls that mutate render as a confirm-card
inside the stream (read-only users simply never get them):

```text
│ you: log 23 g used on the sunlu black petg                                 │
│                                                                            │
│ ai:  ┌─ CONFIRM WRITE ────────────────────────────┐                        │
│      │ Use filament — spool #31 Sunlu PETG Black  │                        │
│      │ remaining:  498 g  ->  475 g   (-23 g)     │                        │
│      │         [ Confirm ]    [ Cancel ]          │                        │
│      └────────────────────────────────────────────┘                        │
│ ai:  Done — spool #31 is now at 475 g.  (undo)                             │
```

### 6.4 B2 Natural-language search → ordinary filter chips

The [ AI ] button next to the search box (present only while the feature is on):

```text
┌─ Spools ───────────────────────────────────────────────────────────────────┐
│  [ matte black under 500 g in shelf B                            ] [ AI ]  │
│  parsing with qwen3:8b …                                                   │
│                                                                            │
│  result is plain, editable filter chips — transparent, no black box:       │
│  [ color ~ black  x ][ finish: matte  x ][ remaining < 500 g  x ]          │
│  [ location: Shelf B  x ]                                     clear all    │
│  ┌──┬──────────────────────┬────────┬──────────┐                           │
│  │id│ filament             │ left   │ location │      3 results            │
└────────────────────────────────────────────────────────────────────────────┘
```

Unparseable input degrades to the existing free-text search — the AI button never
blocks the normal path.

### 6.5 D1 Voice input — states of the chat input strip

```text
idle         │ [ mic ]  [ type a message…                         ] [ send ] │
hold-to-talk │ [ rec 0:03  ▁▂▅▂▇▅▂▁  release to transcribe · slide to cancel]│
transcribing │ [ transcribing on gaming-pc… ]                                │
review       │ [ mic ]  [ log 23 grams on the sunlu black petg   ] [ send ]  │
             │          transcript lands editable in the box, then send      │
             │          (opt-in auto-send toggle in Settings -> AI)          │
replies      │ header "speak replies: on" reads answers aloud via browser    │
             │ speechSynthesis (no backend); server TTS optional later       │
```

Transcribe-then-review is the default because STT mistakes on vendor names are
likely ("Sunlu" -> "sun blue"); auto-send stays an explicit opt-in.

