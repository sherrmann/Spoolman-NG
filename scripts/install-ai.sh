#!/bin/bash -e

# Optional local AI runtime for Spoolman-NG (#364, F3). Provision, don't embed:
# this runs Ollama's own installer and points Spoolman's .env at it — Spoolman
# never bundles an inference engine or model weights, and never manages the
# runtime beyond this setup. Also reachable as `install.sh --with-ai`.
#
# Hard-gated on supported hardware: refuses 32-bit ARM (no Ollama build; the
# hardware cannot hold a useful model) and low-RAM machines, with remote-endpoint
# guidance instead — Spoolman itself is unaffected either way.

GREEN='\033[0;32m'
ORANGE='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

SUDO=sudo
if [ "$EUID" -eq 0 ]; then
    SUDO=
fi

# CD to project root if we're in the scripts dir
current_dir=$(pwd)
if [ "$(basename "$current_dir")" = "scripts" ]; then
    cd ..
fi

#
# Hardware gate: arch first, then RAM.
#
arch="$(uname -m)"
if [ "$arch" != "x86_64" ] && [ "$arch" != "aarch64" ] && [ "$arch" != "arm64" ]; then
    echo -e "${ORANGE}No local AI on $arch: Ollama has no 32-bit ARM build, and this class of hardware cannot hold a useful model in memory.${NC}"
    echo -e "${ORANGE}Spoolman itself is unaffected. Point Settings -> AI at an Ollama on another machine on your network, or at a cloud provider. See docs/ai.md.${NC}"
    exit 1
fi

total_ram_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
# ~3.4 GB: enough for a 4 GB machine (Pi 4/5) after headroom; anything less
# cannot run even small models alongside Spoolman.
if [ "$total_ram_kb" -gt 0 ] && [ "$total_ram_kb" -lt 3500000 ]; then
    echo -e "${ORANGE}Less than ~4 GB RAM detected: even small models will not run usefully here.${NC}"
    echo -e "${ORANGE}Point Settings -> AI at an endpoint on a bigger machine instead. See docs/ai.md.${NC}"
    exit 1
fi

#
# Install Ollama with its official installer (idempotent: skips when present).
#
if command -v ollama &> /dev/null; then
    echo -e "${GREEN}Ollama is already installed - leaving it untouched.${NC}"
else
    echo -e "${GREEN}Installing Ollama (https://ollama.com) with its official installer...${NC}"
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Ollama's installer registers and starts its systemd unit; make sure it is
# enabled and running even if it was installed some other way.
if command -v systemctl &> /dev/null; then
    $SUDO systemctl enable ollama 2>/dev/null || true
    $SUDO systemctl start ollama 2>/dev/null || true
fi

#
# Prefill the Spoolman .env so Settings -> AI is one model choice away.
#
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
fi
if [ -f ".env" ]; then
    if grep -q "^SPOOLMAN_AI_BASE_URL=" .env; then
        echo -e "${GREEN}SPOOLMAN_AI_BASE_URL is already set in .env - leaving it as it is.${NC}"
    else
        {
            echo ""
            echo "# Local AI endpoint set up by scripts/install-ai.sh. See docs/ai.md."
            echo "SPOOLMAN_AI_BASE_URL=http://localhost:11434/v1"
        } >> .env
        echo -e "${GREEN}SPOOLMAN_AI_BASE_URL has been set in .env.${NC}"
        # Pick up the new environment if the service is already registered.
        if [ -f "/etc/systemd/system/Spoolman.service" ] && command -v systemctl &> /dev/null; then
            $SUDO systemctl restart Spoolman 2>/dev/null || true
        fi
    fi
fi

echo -e "${GREEN}Local AI is ready. Open Settings -> AI in Spoolman: the endpoint is prefilled -${NC}"
echo -e "${GREEN}run '${CYAN}Test connection${GREEN}', pull a recommended model from there, and enable the features you want.${NC}"
