#!/usr/bin/env bash
set -euo pipefail

# Installs the Spoolman NG community extension into a KIAUH v6 checkout.
#
#   bash install-extension.sh [path-to-kiauh]      # default: ~/kiauh
#
# or straight from GitHub, without cloning Spoolman-NG:
#
#   curl -fsSL https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/integrations/kiauh/install-extension.sh | bash
#
# When run from a Spoolman-NG checkout the extension files next to this script
# are copied; otherwise they are downloaded from the master branch.

KIAUH_DIR="${1:-$HOME/kiauh}"
EXT_DIR="$KIAUH_DIR/kiauh/extensions/spoolman_ng"
RAW_BASE="https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/integrations/kiauh/spoolman_ng"
FILES=(__init__.py metadata.json spoolman_ng.py spoolman_ng_extension.py)

if [ ! -d "$KIAUH_DIR/kiauh/extensions" ]; then
    echo "KIAUH v6 not found at $KIAUH_DIR (no kiauh/extensions directory)."
    echo "Clone it first:  git clone https://github.com/dw-0/kiauh.git ~/kiauh"
    echo "Or pass its path: bash install-extension.sh /path/to/kiauh"
    exit 1
fi

mkdir -p "$EXT_DIR"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-.}")" &>/dev/null && pwd)
if [ -f "$script_dir/spoolman_ng/spoolman_ng_extension.py" ]; then
    echo "Copying the extension from $script_dir/spoolman_ng ..."
    for f in "${FILES[@]}"; do
        cp "$script_dir/spoolman_ng/$f" "$EXT_DIR/$f"
    done
else
    echo "Downloading the extension into $EXT_DIR ..."
    for f in "${FILES[@]}"; do
        curl -fsSL "$RAW_BASE/$f" -o "$EXT_DIR/$f"
    done
fi

echo
echo "Spoolman NG extension installed to $EXT_DIR"
echo "Start KIAUH and pick [E]xtensions -> Spoolman NG (native install)."
