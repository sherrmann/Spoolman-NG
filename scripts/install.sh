#!/bin/bash -e

# ANSI color codes
GREEN='\033[0;32m'
ORANGE='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Warn with a prompt if we're running as root
SUDO=sudo
if [ "$EUID" -eq 0 ]; then
    echo -e "${ORANGE}WARNING: You are running this script as root. It is recommended to run this script as a non-root user.${NC}"
    echo -e "${ORANGE}Do you want to continue? (y/n)${NC}"
    read choice

    if [ "$choice" != "y" ] && [ "$choice" != "Y" ]; then
        echo -e "${ORANGE}Aborting installation.${NC}"
        exit 1
    fi

    SUDO=
fi

# CD to project root if we're in the scripts dir
current_dir=$(pwd)
if [ "$(basename "$current_dir")" = "scripts" ]; then
    cd ..
fi

#
# Parse arguments (order-independent). -systemd=yes/no keeps its historic meaning
# (KIAUH passes it positionally); --with-ai opts into a local Ollama AI runtime (#364).
#
systemd_option=""
with_ai="no"
for arg in "$@"; do
    case "$arg" in
        -systemd=yes) systemd_option="yes" ;;
        -systemd=no)  systemd_option="no" ;;
        --with-ai)    with_ai="yes" ;;
        *) echo -e "${ORANGE}Ignoring unknown argument: $arg${NC}" ;;
    esac
done

#
# Install uv if not installed
#
local_uv_dir="$(pwd)/uv"
local_uv_bin="$local_uv_dir/uv"

if command -v uv &> /dev/null; then
    echo "uv found in PATH. Using system uv."
else
    if [ -x "$local_uv_bin" ]; then
        if "$local_uv_bin" --version &> /dev/null; then
            echo "Using local uv from $local_uv_dir"
            export PATH="$local_uv_dir:$PATH"
        else
            echo "Local uv found but failed to run. Installing temporary uv..."
            curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$local_uv_dir" sh
            export PATH="$local_uv_dir:$PATH"
        fi
    else
        echo "Installing temporary uv..."
        curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$local_uv_dir" sh
        export PATH="$local_uv_dir:$PATH"
    fi
fi

#
# Get os package manager
#
if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    if [[ "$ID_LIKE" == *"debian"* || "$ID" == *"debian"* ]]; then
        pkg_manager="apt-get"
        update_cmd="$SUDO $pkg_manager update"
        install_cmd="$SUDO $pkg_manager install -y"
        echo -e "${GREEN}Detected Debian-based system. Using apt-get package manager.${NC}"
    elif [[ "$ID_LIKE" == *"arch"* || "$ID" == *"arch"* ]]; then
        pkg_manager="pacman"
        update_cmd="$SUDO $pkg_manager -Sy"
        install_cmd="$SUDO $pkg_manager -S --noconfirm"
        echo -e "${GREEN}Detected Arch-based system. Using pacman package manager.${NC}"
    elif [[ "$ID_LIKE" == *"fedora"* || "$ID" == *"fedora"* ]]; then
        pkg_manager="dnf"
        # makecache, not "dnf update": the latter is a full system upgrade and prompts (#272).
        update_cmd="$SUDO $pkg_manager makecache"
        install_cmd="$SUDO $pkg_manager install -y"
        echo -e "${GREEN}Detected Fedora-based system. Using dnf package manager.${NC}"
    else
        echo -e "${ORANGE}Unsupported Linux distribution. Please install the required dependencies manually.${NC}"
    fi
fi

# Run pkg manager update
packages=""
if ! command -v pg_config &>/dev/null; then
    echo -e "${ORANGE}pg_config is not available. Installing libpq-dev...${NC}"
    if [[ "$pkg_manager" == "apt-get" ]]; then
        packages+=" libpq-dev"
    elif [[ "$pkg_manager" == "pacman" ]]; then
        packages+=" postgresql-libs"
    elif [[ "$pkg_manager" == "dnf" ]]; then
        packages+=" libpq-devel"
    else
        echo -e "${ORANGE}pg_config not found and automatic installation not supported for this OS. Please install libpq-dev or postgresql-libs manually.${NC}"
    fi
fi

# On 32-bit ARM (armv7/armv6) there are no prebuilt wheels for several
# dependencies (psycopg2-binary, asyncpg, greenlet, cffi, ...), so they are
# compiled from source and need a C/C++ toolchain plus dev headers. amd64/arm64
# install from wheels and skip this. Mirrors the build deps in the Dockerfile.
arch="$(uname -m)"
if [[ "$arch" == "armv7l" || "$arch" == "armv6l" || "$arch" == "armhf" ]] && ! command -v gcc &>/dev/null; then
    echo -e "${ORANGE}32-bit ARM detected; installing build tools for compiling dependencies from source...${NC}"
    if [[ "$pkg_manager" == "apt-get" ]]; then
        packages+=" g++ python3-dev libffi-dev"
    elif [[ "$pkg_manager" == "pacman" ]]; then
        packages+=" base-devel libffi"
    elif [[ "$pkg_manager" == "dnf" ]]; then
        packages+=" gcc-c++ python3-devel libffi-devel"
    else
        echo -e "${ORANGE}Could not auto-install build tools. Please install a C/C++ compiler, Python dev headers, and libffi manually.${NC}"
    fi
fi

# not needed?
# if ! command -v unzip &>/dev/null; then
#     echo -e "${ORANGE}unzip is not available. Installing unzip...${NC}"
#     packages+=" unzip"
# fi

if [[ -n "$packages" ]]; then
    $update_cmd || exit 1
    $install_cmd $packages || exit 1
fi

#
# Install Spoolman
#

# Install dependencies
echo -e "${GREEN}Installing Spoolman backend and its dependencies...${NC}"

uv sync --no-dev

# Moonraker's update manager installs dependency updates through `<venv>/bin/pip` and
# silently skips them when it is missing (#263). uv-created venvs ship without pip, so
# seed it (uv installs into ./.venv; works regardless of the base python's ensurepip).
uv pip install pip

#
# Initialize the .env file if it doesn't exist
#
if [ ! -f ".env" ]; then
    echo -e "${ORANGE}.env file not found. Creating it...${NC}"
    cp .env.example .env
fi

#
# Optional local AI (#364): install the Ollama runtime and point Spoolman at it.
# We manage models later from Settings -> AI; the runtime is all that's set up here,
# and no model weights are downloaded. Arch/RAM-gated — Ollama has no 32-bit ARM build.
#
if [ "$with_ai" == "yes" ]; then
    ai_arch="$(uname -m)"
    total_mem_gb=0
    if [ -r /proc/meminfo ]; then
        total_mem_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
        # Guard the arithmetic: a missing/odd MemTotal would otherwise abort the whole
        # script under `set -e`, failing an install over a cosmetic RAM hint.
        if [[ "$total_mem_kb" =~ ^[0-9]+$ ]]; then
            total_mem_gb=$(( total_mem_kb / 1024 / 1024 ))
        fi
    fi

    if [[ "$ai_arch" == "armv7l" || "$ai_arch" == "armv6l" || "$ai_arch" == "armhf" ]]; then
        # Ollama publishes no 32-bit ARM build — a local runtime cannot run here.
        echo -e "${ORANGE}Local AI (--with-ai) is unavailable on 32-bit ARM: Ollama has no armv7 build.${NC}"
        echo -e "${ORANGE}Run Ollama on another machine (a NAS, desktop or mini-PC) and add to your .env:${NC}"
        echo -e "${ORANGE}  SPOOLMAN_AI_BASE_URL=http://<that-host>:11434/v1${NC}"
        echo -e "${ORANGE}then enable features under Settings -> AI. Skipping the local AI install.${NC}"
    else
        if [ "$total_mem_gb" -gt 0 ] && [ "$total_mem_gb" -lt 4 ]; then
            echo -e "${ORANGE}Note: ~${total_mem_gb} GB RAM detected. Local models still run, but stick to small ones${NC}"
            echo -e "${ORANGE}(e.g. llama3.2:3b); 8 GB+ or a GPU is recommended for the standard models.${NC}"
        fi

        if command -v ollama &> /dev/null; then
            echo -e "${GREEN}Ollama already installed. Skipping the runtime install.${NC}"
        else
            echo -e "${ORANGE}This runs Ollama's official installer from https://ollama.com/install.sh${NC}"
            echo -e "${ORANGE}— third-party code, not maintained by Spoolman. It uses sudo to add a${NC}"
            echo -e "${ORANGE}system user and a systemd service. Skip --with-ai if you'd rather${NC}"
            echo -e "${ORANGE}install Ollama yourself and just set SPOOLMAN_AI_BASE_URL in .env.${NC}"
            echo -e "${GREEN}Installing the Ollama AI runtime...${NC}"
            curl -fsSL https://ollama.com/install.sh | sh
        fi

        # The installer registers and starts a systemd unit on systemd hosts; make sure.
        if command -v systemctl &> /dev/null && [ -d /run/systemd/system ]; then
            $SUDO systemctl enable --now ollama &> /dev/null || true
        fi

        # Point Spoolman at the local endpoint (OpenAI-compatible path under /v1), unless
        # the user already set one. Models are pulled later from Settings -> AI.
        if grep -q "^SPOOLMAN_AI_BASE_URL=" .env 2> /dev/null; then
            echo -e "${GREEN}SPOOLMAN_AI_BASE_URL already set in .env; leaving it unchanged.${NC}"
        else
            sed -i "/^#[[:space:]]*SPOOLMAN_AI_BASE_URL=/d" .env
            echo "SPOOLMAN_AI_BASE_URL=http://127.0.0.1:11434/v1" >> .env
            echo -e "${GREEN}Set SPOOLMAN_AI_BASE_URL=http://127.0.0.1:11434/v1 in .env.${NC}"
        fi

        echo -e "${GREEN}Local AI runtime ready. Open Settings -> AI in Spoolman to pull a model and turn features on.${NC}"
    fi
fi

#
# Add execute permissions of all files in scripts dir
#
echo -e "${GREEN}Adding execute permissions to all files in scripts dir...${NC}"
chmod +x scripts/*.sh

#
# Install systemd service
#
if [ "$systemd_option" == "no" ]; then
   choice="n"
elif [ "$systemd_option" == "yes" ]; then
   choice="y"
elif ! command -v systemctl &> /dev/null; then
   echo -e "${ORANGE}systemctl not found. Skipping systemd service installation.${NC}"
   choice="n"
else
   echo -e "${CYAN}Do you want to install Spoolman as a systemd service? This will automatically start Spoolman when your server starts. (y/n)${NC}"
   read choice
fi

if [ "$choice" == "y" ] || [ "$choice" == "Y" ]; then
    systemd_user_dir="$HOME/.config/systemd/user"
    service_name="Spoolman"

    # Check if user-level systemd service exists and remove it
    if [ -f "$systemd_user_dir/$service_name.service" ]; then
        echo -e "${ORANGE}User-level systemd service already installed. Removing the existing service.${NC}"
        systemctl --user stop Spoolman  # Stop the service if it's running
        systemctl --user disable Spoolman  # Disable the service
        rm "$systemd_user_dir/$service_name.service"  # Remove the user-level service unit file
        systemctl --user daemon-reload  # Reload the systemd user service manager
    fi

    # Get the parent directory of the installer script
    script_dir=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
    spoolman_dir=$(dirname "$script_dir")

    # Verify that we found the right spoolman dir by checking for the existence of pyproject.toml
    if [ ! -f "$spoolman_dir/pyproject.toml" ]; then
        echo -e "${ORANGE}Could not automatically find the Spoolman directory. Please specify the path to the Spoolman directory (the directory containing pyproject.toml):${NC}"
        read spoolman_dir
        # Expand the path
        spoolman_dir=$(eval echo "$spoolman_dir")
        # Verify again
        if [ ! -f "$spoolman_dir/pyproject.toml" ]; then
            echo -e "${ORANGE}Could not find pyproject.toml in $spoolman_dir. Aborting installation.${NC}"
            exit 1
        fi
    fi

    # Define the systemd service unit file
    service_unit="[Unit]
Description=Spoolman

[Service]
Type=simple
ExecStart=bash $spoolman_dir/scripts/start.sh
WorkingDirectory=$spoolman_dir
User=$USER
Restart=always

[Install]
WantedBy=default.target
"

    # Create the systemd service unit file
    service_file="/etc/systemd/system/$service_name.service"
    echo "$service_unit" | $SUDO tee "$service_file" > /dev/null

    # Reload the systemd user service manager
    $SUDO systemctl daemon-reload

    # Enable and start the service
    $SUDO systemctl enable "$service_name"
    $SUDO systemctl start "$service_name"

    # Load .env file now
    set -o allexport
    source .env
    set +o allexport

    local_ip=$(hostname -I | awk '{print $1}')

    echo -e "${GREEN}Spoolman systemd service has been installed and Spoolman is now starting.${NC}"
    echo -e "${GREEN}Spoolman will soon be reachable at ${ORANGE}http://$local_ip:$SPOOLMAN_PORT${NC}"
    echo -e "${GREEN}Please note that the displayed IP address may be incorrect for your setup. If needed, replace it manually with the correct IP.${NC}"
    echo -e "${GREEN}You can start/restart/stop the service by running e.g. '${CYAN}sudo systemctl stop Spoolman${GREEN}'${NC}"
    echo -e "${GREEN}You can disable the service from starting automatically by running '${CYAN}sudo systemctl disable Spoolman${GREEN}'${NC}"
    echo -e "${GREEN}You can view the Spoolman logs by running '${CYAN}sudo journalctl -u Spoolman${GREEN}'${NC}"
else
    echo -e "${ORANGE}Skipping systemd service installation.${NC}"
    echo -e "${ORANGE}You can start Spoolman manually by running 'bash scripts/start.sh'${NC}"
fi

echo -e "${GREEN}Spoolman has been installed successfully!${NC}"
echo -e "${GREEN}If you want to connect to an external database, you can edit the .env file and restart the service.${NC}"
