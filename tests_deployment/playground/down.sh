#!/usr/bin/env bash
# Stop the playground started by up.sh. Pass -v to also remove volumes (Spoolman DB, gcode).
set -euo pipefail
cd "$(dirname "$0")"
PRIND_DIR="$(pwd)/../.cache/prind"
exec docker compose \
  --project-name "${PLAYGROUND_PROJECT:-spoolman-playground}" \
  --profile mainsail --profile spoolman \
  -f "$PRIND_DIR/docker-compose.yaml" \
  -f "$PRIND_DIR/docker-compose.extra.simulavr.yaml" \
  -f "$(pwd)/spoolman-ng.yaml" \
  down "$@"
