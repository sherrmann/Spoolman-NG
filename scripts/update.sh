#!/bin/bash -e
# Update a native Spoolman NG install in place (#271) — the non-Moonraker update path.
#
#   bash scripts/update.sh            # update to the latest release
#   bash scripts/update.sh --tag vX   # update (or roll back) to a specific release
#   bash scripts/update.sh --force    # re-apply even if already on that version
#
# Preserves .env, .venv and the local uv/ toolchain (none of them ship in the zip;
# extraction simply overlays the release files), re-syncs Python dependencies, and
# restarts the Spoolman systemd service when one is installed. Non-interactive.

GREEN='\033[0;32m'
ORANGE='\033[0;33m'
NC='\033[0m'

REPO="sherrmann/Spoolman-NG"

# CD to project root if we're in the scripts dir
if [ "$(basename "$(pwd)")" = "scripts" ]; then
    cd ..
fi

if [ ! -f "release_info.json" ] || [ ! -f "pyproject.toml" ]; then
    echo -e "${ORANGE}This does not look like a Spoolman install (release_info.json/pyproject.toml missing).${NC}"
    echo -e "${ORANGE}Run this from the install directory created by scripts/install.sh.${NC}"
    exit 1
fi

tag=""
force="no"
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) tag="$2"; shift 2 ;;
        --force) force="yes"; shift ;;
        *) echo -e "${ORANGE}Unknown argument: $1${NC}"; exit 1 ;;
    esac
done

current=$(grep -o '"version": *"[^"]*"' release_info.json | head -1 | sed 's/.*"\(v[^"]*\)"$/\1/')

if [ -z "$tag" ]; then
    tag=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" |
        grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"\(v[^"]*\)"$/\1/')
    if [ -z "$tag" ]; then
        echo -e "${ORANGE}Could not determine the latest release from GitHub.${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}Installed: ${current:-unknown} — target: ${tag}${NC}"
if [ "$current" = "$tag" ] && [ "$force" != "yes" ]; then
    echo -e "${GREEN}Already up to date (use --force to re-apply).${NC}"
    exit 0
fi

#
# Download and overlay the release. .env, .venv and uv/ are not part of the zip,
# so they survive; everything the release ships is replaced.
#
tmp_zip=$(mktemp --suffix=.zip)
trap 'rm -f "$tmp_zip"' EXIT
echo -e "${GREEN}Downloading ${tag}...${NC}"
curl -fsSL "https://github.com/${REPO}/releases/download/${tag}/spoolman.zip" -o "$tmp_zip"

echo -e "${GREEN}Extracting over the install...${NC}"
unzip -o -q "$tmp_zip" -d .
chmod +x scripts/*.sh

#
# Re-sync dependencies with the same uv the installer set up (system or local).
#
if command -v uv &> /dev/null; then
    :
elif [ -x "$(pwd)/uv/uv" ]; then
    export PATH="$(pwd)/uv:$PATH"
else
    echo -e "${ORANGE}uv not found — run 'bash scripts/install.sh' instead.${NC}"
    exit 1
fi

extra_args=()
if [ -x ".venv/bin/python" ] && .venv/bin/python -c "import nfc" &> /dev/null; then
    echo -e "${GREEN}NFC extra detected in the existing environment; keeping it.${NC}"
    extra_args=(--extra nfc)
fi

echo -e "${GREEN}Syncing Python dependencies...${NC}"
uv sync --no-dev "${extra_args[@]}"
# Moonraker installs dependency updates through <venv>/bin/pip (#263); keep it present.
uv pip install pip

#
# Restart the systemd service if the installer registered one.
#
SUDO=sudo
[ "$EUID" -eq 0 ] && SUDO=
if command -v systemctl &> /dev/null && systemctl list-unit-files Spoolman.service &> /dev/null && \
   systemctl list-unit-files Spoolman.service | grep -q '^Spoolman.service'; then
    echo -e "${GREEN}Restarting the Spoolman service...${NC}"
    $SUDO systemctl try-restart Spoolman
else
    echo -e "${ORANGE}No Spoolman systemd service found — restart Spoolman manually (bash scripts/start.sh).${NC}"
fi

echo -e "${GREEN}Updated to ${tag}.${NC}"
