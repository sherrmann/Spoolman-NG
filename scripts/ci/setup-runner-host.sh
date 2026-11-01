#!/usr/bin/env bash
# One-off preparation of the self-hosted CI runner host (Ubuntu 24.04, arm64 or x86_64).
#
# Installs what the CI jobs routed to the self-hosted runner expect to find on the host, so that
# no job has to change the host itself (see docs/ci-runner.md):
#   - the Docker CLI with the compose plugin (guide-tests: docker compose config, which only renders
#     files); the daemon is switched off and the runner user is not put in the docker group, which
#     would give root to any code a job runs
#   - nginx and Caddy for the docs block check, with their services disabled
#   - the system libraries Playwright's Chromium needs, for the versions the browser test suites pin
#   - git, curl, jq, unzip
#
# Run as root on the runner host:
#   sudo scripts/ci/setup-runner-host.sh
# Safe to run again, e.g. after a Playwright upgrade.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root (sudo)" >&2
  exit 2
fi
# shellcheck source=/dev/null
. /etc/os-release
if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
  # actions/setup-python only has builds for Ubuntu releases, and 24.04 is the oldest whose own
  # archive has Caddy.
  echo "this script expects Ubuntu 24.04; found ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi
repo="$(cd "$(dirname "$0")/../.." && pwd)"

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git curl jq unzip ca-certificates docker.io docker-compose-v2 nginx caddy

# Only the binaries are wanted: a running nginx or Caddy would hold port 80 on the runner host, and
# no job needs the Docker daemon.
systemctl disable --now nginx caddy docker.service docker.socket

# Playwright's own list of Chromium's system libraries, for each version the repo pins. Its CLI
# needs a newer Node.js than Ubuntu ships, so a checksum-verified official Node.js 22 is unpacked
# into a temporary directory for this and removed afterwards.
case "$(uname -m)" in
  x86_64) node_arch=x64 ;;
  aarch64) node_arch=arm64 ;;
  *) echo "no Node.js build for $(uname -m)" >&2; exit 1 ;;
esac
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
base="https://nodejs.org/dist/latest-v22.x"
curl -fsSL -o "$tmp/SHASUMS256.txt" "$base/SHASUMS256.txt"
tarball="$(grep -oE "node-v[0-9.]+-linux-${node_arch}\.tar\.xz$" "$tmp/SHASUMS256.txt")"
curl -fsSL -o "$tmp/$tarball" "$base/$tarball"
(cd "$tmp" && grep " $tarball\$" SHASUMS256.txt | sha256sum -c -)
tar -xJf "$tmp/$tarball" -C "$tmp"
export PATH="$tmp/${tarball%.tar.xz}/bin:$PATH"
for dir in client tests_frontend_v2 tests_frontend_ng; do
  version="$(jq -r '.packages["node_modules/playwright-core"].version' "$repo/$dir/package-lock.json")"
  echo "Installing Chromium's system libraries for Playwright $version ($dir)"
  npm_config_cache="$tmp/npm" npx -y "playwright@$version" install-deps chromium
done

echo "Done."
