# Interactive install guide (`guide/`)

The setup wizard published at <https://sherrmann.github.io/Spoolman-NG/install/> (issue #297):
answer a few questions — goal, platform, Klipper, database, reverse proxy, extras — and get an
ordered step list with ready-to-paste artifacts (docker-compose.yml, `.env`, Helm values.yaml,
moonraker.conf stanzas, proxy config), including the conditional rules static docs can't enforce
(e.g. Klipper + API token → the token is dropped with a warning, #268).

A standalone npm/Vite/React project — deliberately **not** sharing the `client/` toolchain
(no refine/antd). All logic is framework-free under `src/model/`; the UI is a thin render of
`buildPlan(config)`.

## Commands

```bash
npm ci               # install
npm run dev          # local dev server
npm test             # unit + snapshot + drift tests (vitest)
npm run build        # typecheck + production build to dist/
npm run render-matrix -- --out .matrix   # write every preset's artifacts for external validation
```

CI (`guide-tests` job in `.github/workflows/ci.yml`) runs lint/typecheck/tests/build, then
validates the rendered preset matrix with the real tools: `docker compose config` on every
generated compose file and `helm template charts/spoolman-ng` on every generated values.yaml.
Deployment happens in `.github/workflows/docs-site.yml`: the built `dist/` is staged into the
Pages artifact at `docs/install/` (gitignored, like the generated `docs/index.html`).

## Single-source contract

The same snippet must never be maintained twice. Where each kind of content lives:

- **Verbatim stanzas** (`fragments/*`): the canonical copies of the snippets embedded in
  `docs/installation.md` (and `README.md` where noted) — Moonraker `[spoolman]` /
  `[update_manager Spoolman]`, the Caddy/nginx examples, the install/update one-liners, the
  `release_info.json` fix. Placeholders use `{{UPPER_SNAKE}}`; rendering throws on unresolved
  or unused variables.
- **Structurally-varying artifacts** (`src/model/artifacts/`): docker-compose.yml, `.env`,
  Helm values.yaml are TypeScript generators, because their shape changes with the answers.
- **Prose**: `docs/installation.md` stays the complete human reference.

**Drift tests** (`src/drift/`) keep the three in lock-step and fail the build when one side
changes without the others:

- each fragment, rendered with its documented example values, must equal the fenced block in
  `docs/installation.md` / `README.md` located by an anchor substring;
- the default compose output must match the root `docker-compose.yml` (and the docs' quick-start
  block) semantically;
- every emitted `SPOOLMAN_*`/`PUID`/`PGID` variable must exist in `.env.example`;
- every emitted top-level Helm values key must exist in `charts/spoolman-ng/values.yaml`.

So: **edit the fragment and the doc together** (or the canonical file and the generator), run
`npm test`, and commit both sides. The KIAUH extension (`integrations/kiauh/`) and
`tests_deployment/test_moonraker_updater.py` carry copies of the Moonraker stanzas in other
languages; they are pinned indirectly via the doc blocks these tests check.

## Adding a rule or platform

1. Extend the types in `src/model/config.ts` (and `relevantQuestions` if the answer only
   matters sometimes).
2. Put config-mutating rules in `src/model/rules.ts` (`normalizeConfig`), artifact changes in
   the generator, new steps in `src/model/steps.ts`.
3. Add a focused test next to the module and, if the change creates a new output shape, a
   preset in `src/model/presets.ts` — presets feed both the snapshot suite and CI's
   compose/helm validation.
