#!/usr/bin/env bash
# Deployment-channel test harness (#277) — run from anywhere:
#   tests_deployment/run.sh              # everything in Tier 1
#   tests_deployment/run.sh zip          # release-zip + release-metadata contract (fast, no docker)
#   tests_deployment/run.sh addon        # Home Assistant add-on options contract
#   tests_deployment/run.sh native       # install.sh matrix (debian/fedora/arch containers)
#   tests_deployment/run.sh moonraker    # real Moonraker validates the type:zip recipe
# Extra arguments go to pytest, e.g.:  tests_deployment/run.sh native -k debian
set -euo pipefail
cd "$(dirname "$0")/.."

target="${1:-tier1}"
[ "$#" -gt 0 ] && shift

case "$target" in
  tier1)     paths=(tests_deployment/test_tier1_*.py) ;;
  zip)       paths=(tests_deployment/test_tier1_zip_contract.py) ;;
  addon)     paths=(tests_deployment/test_tier1_ha_addon.py) ;;
  native)    paths=(tests_deployment/test_tier1_native_install.py) ;;
  moonraker) paths=(tests_deployment/test_tier1_moonraker.py) ;;
  *)         paths=("$target") ;;
esac

exec uv run pytest -v -ra "${paths[@]}" "$@"
