#!/bin/sh

PUID=${PUID:-1000}
PGID=${PGID:-1000}
SPOOLMAN_PORT=${SPOOLMAN_PORT:-8000}
SPOOLMAN_HOST=${SPOOLMAN_HOST:-0.0.0.0}

fail() {
    echo "$1" >&2
    exit 1
}

if [ "$(id -u)" -eq 0 ]; then
    # Running as root: apply PUID/PGID remapping, then drop privileges (#239).
    # PUID/PGID must be numeric and non-zero — 0 would gosu-re-exec as root forever.
    [ "$PUID" -ne 0 ] 2>/dev/null || fail "Invalid PUID '$PUID': must be a non-zero UID"
    [ "$PGID" -ne 0 ] 2>/dev/null || fail "Invalid PGID '$PGID': must be a non-zero GID"

    if [ "$(id -u app)" -ne "$PUID" ]; then
        usermod -o -u "$PUID" app ||
            fail "Failed to update app UID to $PUID"
    fi

    if [ "$(id -g app)" -ne "$PGID" ]; then
        groupmod -o -g "$PGID" app ||
            fail "Failed to update app GID to $PGID"
    fi

    # Make sure the data dir is owned by the (possibly remapped) app user, so fresh
    # root-owned volumes and PUID changes across restarts just work. Also heals setups
    # that relied on the pre-2026.7.1 supplementary gid-1000 'users' group for write
    # access (the upstream-#960 class of breakage).
    data_dir="${SPOOLMAN_DIR_DATA:-/home/app/.local/share/spoolman}"
    if [ -d "$data_dir" ] && [ "$(stat -c %u "$data_dir")" -ne "$PUID" ]; then
        echo "Fixing ownership of $data_dir to $PUID:$PGID"
        chown -R "$PUID:$PGID" "$data_dir" || true
    fi

    # Fix USB device permissions for NFC reader access. Needs root; containers
    # started with --user rely on the host granting device access instead.
    if [ -d /dev/bus/usb ]; then
        chmod -R o+rw /dev/bus/usb/ 2>/dev/null || true
    fi

    exec gosu "app" "$0" "$@"
    # NOT REACHABLE
fi

# Already non-root (docker run --user, Kubernetes runAsNonRoot, OpenShift random
# UID): remapping is impossible without root, so PUID/PGID are ignored (#239).
if [ "$(id -u)" -ne "$PUID" ] || [ "$(id -g)" -ne "$PGID" ] 2>/dev/null; then
    echo "Running unprivileged as $(id -u):$(id -g); ignoring PUID/PGID ($PUID/$PGID). Use --user (or securityContext) to pick the UID/GID instead." >&2
fi

echo "Starting uvicorn..."

exec uvicorn spoolman.main:app --host $SPOOLMAN_HOST --port $SPOOLMAN_PORT "$@"
