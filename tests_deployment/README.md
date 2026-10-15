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
tests_deployment/run.sh native       # install.sh matrix + update.sh upgrade path; -k debian for one distro
tests_deployment/run.sh moonraker    # real Moonraker validates the updater recipe
tests_deployment/run.sh runtime      # virtual-printer e2e: a print consumes filament in Spoolman
tests_deployment/run.sh helm         # chart install into a throwaway k3d cluster (needs helm/k3d/kubectl)
tests_deployment/run.sh octoprint    # OctoPrint-Spoolman plugin against token-protected NG
tests_deployment/run.sh hacs         # Home Assistant Core loads the HACS integration
tests_deployment/run.sh upgrade      # data survives previous-image -> latest on the same volume
tests_deployment/run.sh guide        # wizard-generated Postgres/MariaDB sidecar compose files actually boot
```

Requirements: `uv` (repo dev env), Docker for everything except `zip`, network access,
~2 GB of image pulls on the first run. `guide` additionally renders the wizard presets
with Node (the `guide/` npm project), or reuses a pre-rendered matrix via
`SPOOLMAN_GUIDE_MATRIX`; it skips when neither is available.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `SPOOLMAN_RELEASE_TAG` | latest release | Which published release to test |
| `SPOOLMAN_ZIP_PATH` | unset | Test a locally built zip instead of a published release (GitHub-release-metadata tests skip) — used to verify fixes before they ship |
| `SPOOLMAN_IMAGE` | `ghcr.io/sherrmann/spoolman-ng:latest` | Server image the add-on wraps (and the `guide` compose stacks boot) |
| `SPOOLMAN_GUIDE_MATRIX` | unset | Pre-rendered guide preset matrix for the `guide` suite; skips the Node render step |
| `SPOOLMAN_ADDON_REPO_PATH` | sibling checkout or fresh clone | Path to `spoolman-ng-addons` |
| `GITHUB_TOKEN` | `gh auth token` if available | Raises GitHub API rate limits |
| `SPOOLMAN_DEPLOY_KEEP` | unset | Keep containers after a run for debugging |

Downloads are cached in `tests_deployment/.cache/` (gitignored). Leaked containers are
labelled: `docker ps -aq --filter label=spoolman-deploy-test | xargs -r docker rm -f`.

## What red means

A failure means one of two things: a published artefact (release zip, image, installer,
add-on or chart) really is broken, or a third party the harness runs against (Moonraker,
Home Assistant, OctoPrint, a distro image or mirror) has changed underneath us. Either
way it is worth a look; the failing assertion says which. The earlier known gaps
(#261-#264 and #272) were fixed in #278 and #289, so a clean run is the expected state.

## Runs in CI

`.github/workflows/deployment-harness.yml` runs the harness on GitHub-hosted runners
against the published release and its pinned image (`ghcr.io/<owner>/spoolman-ng:<version>`):

- **Release set**, dispatched by `publish-release` in `ci.yml` after each release:
  `zip`, `moonraker`, `native` (Debian amd64 only) and `upgrade`.
- **Weekly set**, Mondays at 06:15 UTC: `zip`, `addon`, `native`, `moonraker`, `helm`,
  `octoprint`, `hacs`, `upgrade` and `guide` (without the `slow` Ollama test).

`runtime` is not run in CI (it needs a 5.4 GB simulavr build), and `native` skips its
Debian arm64 case on runners without qemu binfmt. Each suite is retried once within its
job, since third-party hosts are flaky. When a suite still fails, its junit report and
container logs are attached to the run for 14 days.

A failing release or weekly run opens (or updates) a single issue titled "Deployment
harness failing", labelled `deployment-harness`. It lists the failing suites and links
the run, gets a new comment only when that set changes, and is closed by the first fully
green run afterwards.

To run it by hand, from the Actions tab or with the GitHub CLI:

```bash
gh workflow run deployment-harness.yml -f tag=vX -f suites=release
gh workflow run deployment-harness.yml -f suites=helm    # one suite, latest release
```

`tag` defaults to the latest release; `suites` takes `release`, `weekly` or one suite name.
A single-suite run does not touch the tracking issue.

## Roadmap (#277)

This directory holds the channel contracts plus the virtual-printer runtime e2e
(`test_moonraker_runtime.py`, built on [playground/](playground/) — it skips unless
the simulavr MCU image has been built once via `playground/up.sh`) and the install
guide's database-sidecar boot test (`test_guide_compose.py`, #341 — it brings the
wizard's Postgres/MariaDB compose presets up for real, beyond the `docker compose
config` syntax check the `guide-tests` PR job already does). Planned
additions (tracked as tiers in #277, but organised here by what they test): the
OctoPrint plugin, HA Core + the HACS integration, and k3d + Helm; the heavyweight
appliance checks (HAOS Supervisor install, nested Proxmox, NixOS module) stay
manual.
