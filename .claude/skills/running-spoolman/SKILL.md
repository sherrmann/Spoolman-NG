---
name: running-spoolman
description: Launch Spoolman locally (backend + built client) and drive it in a browser to see or screenshot a UI change. Use when asked to run or start the app, screenshot a page, or confirm a change works in the real app rather than in tests.
---

# Running Spoolman locally

Spoolman is a FastAPI backend that also serves the built React client. There is no separate
front-end dev server in this workflow: the backend serves `client/dist`, so **a client change is
invisible until you rebuild _and_ restart**.

## Launch

`alembic` must be on `PATH` or startup dies with `FileNotFoundError: 'alembic'` — it lives in
`.venv/bin`, which is not on `PATH` by default. Put the launch in a script rather than inlining it,
so a later `pkill -f <pattern>` cannot match the launching command's own arguments and kill the
shell (exit 144).

```bash
cat > /tmp/spoolman-boot.sh <<'SH'
#!/usr/bin/env bash
cd /home/sam/spoolman/Spoolman
export PATH="/home/sam/spoolman/Spoolman/.venv/bin:$PATH"
export SPOOLMAN_DB_TYPE=sqlite
export SPOOLMAN_DIR_DATA=/tmp/spoolman-data   # throwaway DB; never point at real data
exec .venv/bin/uvicorn spoolman.main:app --host 127.0.0.1 --port 8765
SH
chmod +x /tmp/spoolman-boot.sh
mkdir -p /tmp/spoolman-data
nohup /tmp/spoolman-boot.sh > /tmp/spoolman.log 2>&1 &
until curl -sf http://127.0.0.1:8765/api/v1/info >/dev/null; do sleep 1; done
```

Stop it by port, never by pattern:

```bash
PID=$(ss -lptnH "sport = :8765" | grep -oP 'pid=\K[0-9]+' | head -1); [ -n "$PID" ] && kill "$PID"
```

## After changing client code

```bash
cd client && npm run build     # ~1-2 min
# then restart the backend -- it reads index.html once at startup and will otherwise keep
# serving the old asset hashes, giving a blank page and 404s for assets/index-*.js
```

## Driving it with Playwright

Use the client's own Playwright and the system chromium (`/usr/bin/chromium`). Headed, always —
Sam wants to watch it. `DISPLAY=:0` is available.

```js
import { chromium } from "/home/sam/spoolman/Spoolman/client/node_modules/playwright/index.mjs";
const browser = await chromium.launch({ headless: false, executablePath: "/usr/bin/chromium" });
// serviceWorkers:"block" is REQUIRED -- the PWA precache otherwise serves a previous build's
// index.html against fresh assets and the page renders blank.
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1800 }, serviceWorkers: "block" });
```

Gotchas that each cost a retry:

- **Settings tabs are not `role=tab`.** `getByRole("tab", ...)` finds nothing; fall back to the
  label text: `page.locator("text=/^AI$/")`. Below ~1440 px wide the tab strip collapses and even
  that fails.
- **`page.screenshot({clip})` truncates** at the painted content edge on these pages. Take
  `fullPage: true` and crop afterwards with ImageMagick (`convert in.png -crop WxH+X+Y +repage out.png`).
- **`scrollIntoViewIfNeeded()` parks the element at the bottom** of the viewport, clipping whatever
  is below it. Use `el.evaluate(e => e.scrollIntoView({block: "start"}))`.

## Settings → AI specifically

The AI tab renders with no endpoint configured, but the **Ollama models** shortlist only mounts
after a successful probe. Configure and probe first, then click *Test connection* in the UI:

```bash
for kv in ai_base_url:'"http://127.0.0.1:11434/v1"' ai_model:'"qwen3:4b-instruct"' ai_vision_model:'"qwen2.5vl:7b"'; do
  curl -s -X POST "http://127.0.0.1:8765/api/v1/setting/${kv%%:*}" \
    -H 'Content-Type: application/json' -d "\"${kv#*:}\"" -o /dev/null
done
```

Point `ai_model` at a model that is actually pulled, or the panel shows red "not supported"
verdicts that look like a bug in the screenshot.

## Screenshots for review

Put them in `ui-review/` (gitignored is fine), name the paths in the message, present before/after
as an explicit standalone review step, and delete them once approved.
