# Deployment-channel tests (#277)

This harness tests Spoolman NG's **distribution channels** — the published release zip,
the native `install.sh` path, Moonraker's updater, and the Home Assistant add-on —
against the real consumers, not re-implementations of them. Unlike `tests/` and
`tests_integration/`, it exercises **published artifacts** (the GitHub release and the
`ghcr.io` image), so it needs network access and is *not* part of PR CI.

## Running

```bash
tests_deployment/run.sh              # all contract suites (~15-25 min cold)
tests_deployment/run.sh zip          # release contract only (seconds, no docker)
tests_deployment/run.sh addon        # HA add-on options contract
tests_deployment/run.sh native       # install.sh matrix; -k debian for one distro
tests_deployment/run.sh moonraker    # real Moonraker validates the updater recipe
tests_deployment/run.sh runtime      # virtual-printer e2e: a print consumes filament in Spoolman
tests_deployment/run.sh helm         # chart install into a throwaway k3d cluster (needs helm/k3d/kubectl)
tests_deployment/run.sh octoprint    # OctoPrint-Spoolman plugin against token-protected NG
tests_deployment/run.sh hacs         # Home Assistant Core loads the HACS integration
```

Requirements: `uv` (repo dev env), Docker for everything except `zip`, network access,
~2 GB of image pulls on the first run.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `SPOOLMAN_RELEASE_TAG` | latest release | Which published release to test |
| `SPOOLMAN_ZIP_PATH` | unset | Test a locally built zip instead of a published release (GitHub-release-metadata tests skip) — used to verify fixes before they ship |
| `SPOOLMAN_IMAGE` | `ghcr.io/sherrmann/spoolman-ng:latest` | Server image the add-on wraps |
| `SPOOLMAN_ADDON_REPO_PATH` | sibling checkout or fresh clone | Path to `spoolman-ng-addons` |
| `GITHUB_TOKEN` | `gh auth token` if available | Raises GitHub API rate limits |
| `SPOOLMAN_DEPLOY_KEEP` | unset | Keep containers after a run for debugging |

Downloads are cached in `tests_deployment/.cache/` (gitignored). Leaked containers are
labelled: `docker ps -aq --filter label=spoolman-deploy-test | xargs -r docker rm -f`.

## What red means

These are **contract tests pinned to open issues** — they are expected to stay red until
the corresponding fix ships in a release:

| Failing assertion | Issue |
|---|---|
| `release_info.json` project name ≠ `Spoolman-NG` | #261 |
| Release title ≠ installed version (phantom update) | #262 |
| No root `requirements.txt` / no pip in `.venv` / updater section rejected | #263 |
| `scripts/*.sh` not executable inside the zip | #264 |
| Fedora installer gaps | #272 |

When a fix lands, its test goes green with no harness change: the harness always tests
the latest (or pinned) release.

## Roadmap (#277)

This directory holds the channel contracts plus the virtual-printer runtime e2e
(`test_moonraker_runtime.py`, built on [playground/](playground/) — it skips unless
the simulavr MCU image has been built once via `playground/up.sh`). Planned
additions (tracked as tiers in #277, but organised here by what they test): the
OctoPrint plugin, HA Core + the HACS integration, and k3d + Helm; the heavyweight
appliance checks (HAOS Supervisor install, nested Proxmox, NixOS module) stay
manual.
