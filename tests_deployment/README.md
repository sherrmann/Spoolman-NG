# Deployment-channel tests (#277)

This harness tests Spoolman NG's **distribution channels** — the published release zip,
the native `install.sh` path, Moonraker's updater, and the Home Assistant add-on —
against the real consumers, not re-implementations of them. Unlike `tests/` and
`tests_integration/`, it exercises **published artifacts** (the GitHub release and the
`ghcr.io` image), so it needs network access and is *not* part of PR CI.

## Running

```bash
tests_deployment/run.sh              # all of Tier 1 (~15-25 min cold)
tests_deployment/run.sh zip          # release contract only (seconds, no docker)
tests_deployment/run.sh addon        # HA add-on options contract
tests_deployment/run.sh native       # install.sh matrix; -k debian for one distro
tests_deployment/run.sh moonraker    # real Moonraker validates the updater recipe
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

## Tiers (see #277)

- **Tier 1** (this directory): channel contracts — fast, deterministic, nightly + post-release.
- **Tier 2** (planned): virtual Klipper printer (prind/simulavr) exercising the runtime
  `[spoolman]` component, OctoPrint plugin, HA Core + HACS integration, k3d + Helm.
- **Tier 3** (planned, manual): HAOS VM installing the add-on repo via the real
  Supervisor, nested Proxmox running the community script, NixOS module test.
