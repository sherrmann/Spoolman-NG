# CI on the self-hosted runner

The test and lint jobs can run on the project's own arm64 machine (an Oracle Cloud Ampere
instance) instead of GitHub's runners. This page says what runs where, how to switch it on and
off, and what the host needs.

## What runs where

| On the self-hosted runner | Stays on GitHub's runners | Why it stays |
|---|---|---|
| `ci.yml`: style, unit-tests, client-tests, client-v2-tests, mobile-tests, guide-tests, e2e, tests-frontend-v2, tests-frontend-ng | `ci.yml`: meta, CodeQL, hadolint | small, and CodeQL's Linux arm64 support is too new to rely on |
| `mutation.yml`: both jobs | the amd64 image build and the image tests (`build-amd64`, `build-tester`, `test`, `test-nonroot`) | they run amd64 images, which an arm64 host can only emulate |
| | `build-arm64`, `build-armv7`, `build-client`, `verify-artifact`, `publish-images`, `publish-release`, `sync-ha-addon`, `deploy-test`, the APK build | they produce release artefacts or hold publishing secrets; these come from clean, throwaway machines |
| | the deployment harness, upstream watch, ledger, docs site, release trigger | they download amd64 tools, need `gh`, or publish |

Pull requests from any other repository (a fork, or upstream) always run on GitHub's runners, so
code from outside the repository never runs on the instance. Pull requests from branches of this
repository, pushes and schedules use the self-hosted runner. (The check compares the pull request's
head repository with this one; GitHub's own `fork` flag would not do, since this repository is
itself a fork of Donkie/Spoolman.)

## Switching it on and off

The routing is controlled by one repository variable, so no commit is needed either way:

- **On:** *Settings → Secrets and variables → Actions → Variables*, add `SELF_HOSTED_RUNNER` with
  the runner's labels as a JSON array: `["self-hosted","linux","ARM64"]`.
- **Off:** delete the variable. The jobs go back to `ubuntu-latest` from the next run. Do this if
  the instance is down: a job waiting for an offline self-hosted runner sits in the queue for up
  to a day before GitHub cancels it.

`ci.yml`'s `meta` job reads the variable and refuses a value that is not a JSON array of labels.

## Preparing the host

The host needs Ubuntu 24.04 (`actions/setup-python` only has builds for Ubuntu releases, and 24.04
has Caddy in its archive). Register the runner with GitHub's default labels and install it as a
service running as an ordinary user, not root. Then, once, from a checkout of this repository:

```sh
sudo scripts/ci/setup-runner-host.sh
```

It installs the Docker CLI with the compose plugin, nginx and Caddy, with their services switched
off (the jobs only render compose files and test configs; the runner user is deliberately not in
the `docker` group, which would give root to any code a job runs), and the system libraries
Playwright's Chromium needs. Run it again after a Playwright upgrade in `client/`,
`tests_frontend_v2/` or `tests_frontend_ng/`.

The jobs themselves leave the host as they found it: Node, Python, uv and Helm are installed per
job by their setup actions (Helm from `.github/actions/setup-helm`, checksum-verified), apt runs
only on GitHub's runners, and Playwright installs system packages (`--with-deps`) only there.

## Things to know

- **One job at a time.** A single runner works through the jobs one by one, where GitHub runs them
  side by side, so a full CI run takes longer in wall time. Keep to one runner per host: the
  browser test jobs use fixed local ports (8001 to 8004), and two of them at once on the same host
  would collide. A second runner belongs on a second host. A job fails if its server cannot
  start, so a server left behind by an earlier job (after the runner service was restarted
  mid-job, say) is noticed rather than tested by mistake.
- **Disk.** The runner keeps its work directory and tool cache between jobs; an occasional look at
  the runner's `_work/_tool` keeps it in check.
- **The runner sees repository secrets passed to the jobs it runs.** None of the jobs routed to it
  use secrets beyond the job's own `GITHUB_TOKEN`; keep it that way when moving more jobs.
