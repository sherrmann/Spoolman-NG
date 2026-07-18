#!/usr/bin/env bash
# Deployment-channel test harness (#277) — run from anywhere:
#   tests_deployment/run.sh              # all contract suites
#   tests_deployment/run.sh zip          # release-zip + release-metadata contract (fast, no docker)
#   tests_deployment/run.sh addon        # Home Assistant add-on options contract
#   tests_deployment/run.sh native       # install.sh matrix (debian/fedora/arch containers)
#   tests_deployment/run.sh moonraker    # real Moonraker validates the update_manager recipe
#   tests_deployment/run.sh runtime      # virtual-printer e2e: a print consumes filament in Spoolman
#   tests_deployment/run.sh helm         # chart install into a throwaway k3d cluster
#   tests_deployment/run.sh octoprint    # OctoPrint-Spoolman plugin against token-protected NG
# Extra arguments go to pytest, e.g.:  tests_deployment/run.sh native -k debian
set -euo pipefail
cd "$(dirname "$0")/.."

target="${1:-all}"
[ "$#" -gt 0 ] && shift

case "$target" in
  all)       paths=(tests_deployment) ;;
  zip)       paths=(tests_deployment/test_release_zip.py) ;;
  addon)     paths=(tests_deployment/test_ha_addon.py) ;;
  native)    paths=(tests_deployment/test_native_install.py) ;;
  moonraker) paths=(tests_deployment/test_moonraker_updater.py) ;;
  runtime)   paths=(tests_deployment/test_moonraker_runtime.py) ;;
  helm)      paths=(tests_deployment/test_helm_chart.py) ;;
  octoprint) paths=(tests_deployment/test_octoprint_plugin.py) ;;
  *)         paths=("$target") ;;
esac

exec uv run pytest -v -ra "${paths[@]}" "$@"
