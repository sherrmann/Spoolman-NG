#!/usr/bin/env bash
# Interactive Moonraker + Mainsail + Spoolman NG playground on a virtual printer.
# Uses the prind stack (Klipper in docker) with a simulavr-emulated MCU, so Mainsail
# is fully functional and prints actually consume filament that Spoolman tracks.
#
#   tests_deployment/playground/up.sh          # start (first run builds the MCU image)
#   tests_deployment/playground/down.sh        # stop (add -v to also drop volumes/data)
#
# URLs once up:  Mainsail http://localhost:8010/   Spoolman http://localhost:8010/spoolman/
# Knobs: SPOOLMAN_NG_TAG (image tag, default latest), PLAYGROUND_HTTP_PORT (default 8010),
# PLAYGROUND_PROJECT (compose project, default spoolman-playground — the e2e test uses
# its own project/port to boot an isolated copy next to a running playground).
set -euo pipefail
cd "$(dirname "$0")"

PRIND_DIR="$(pwd)/../.cache/prind"
if [ ! -d "$PRIND_DIR/.git" ]; then
  git clone --depth 1 https://github.com/mkuf/prind "$PRIND_DIR"
fi

# Enable Moonraker's [spoolman] component (ships commented out in prind).
# In-network, traefik serves Spoolman under /spoolman on entrypoint :80.
if grep -q '^# \[spoolman\]' "$PRIND_DIR/config/moonraker.conf"; then
  sed -i \
    -e 's|^# \[spoolman\]|[spoolman]|' \
    -e 's|^# server: http://<yourprinter>/spoolman|server: http://traefik/spoolman|' \
    "$PRIND_DIR/config/moonraker.conf"
fi

exec docker compose \
  --project-name "${PLAYGROUND_PROJECT:-spoolman-playground}" \
  --profile mainsail --profile spoolman \
  -f "$PRIND_DIR/docker-compose.yaml" \
  -f "$PRIND_DIR/docker-compose.extra.simulavr.yaml" \
  -f "$(pwd)/spoolman-ng.yaml" \
  up -d --build "$@"
