#!/bin/sh
# Home Assistant add-on launcher (#89): translate add-on options into the SPOOLMAN_* environment
# variables the server reads, keep data in the persistent /data volume, then hand off to the image's
# own entrypoint (which drops privileges and starts uvicorn).
set -e

OPTIONS=/data/options.json

# Read one add-on option from the options JSON using the Python already in the image. Prints an
# empty string when the key is missing or null.
opt() {
    python3 -c "import json;v=json.load(open('${OPTIONS}')).get('$1');print('' if v is None else v)" 2>/dev/null || true
}

if [ -f "${OPTIONS}" ]; then
    db_type=$(opt db_type)
    # sqlite is the default; only set the type env for the external databases.
    if [ -n "${db_type}" ] && [ "${db_type}" != "sqlite" ]; then
        export SPOOLMAN_DB_TYPE="${db_type}"
    fi
    v=$(opt db_host); [ -n "${v}" ] && export SPOOLMAN_DB_HOST="${v}"
    v=$(opt db_port); [ -n "${v}" ] && export SPOOLMAN_DB_PORT="${v}"
    v=$(opt db_name); [ -n "${v}" ] && export SPOOLMAN_DB_NAME="${v}"
    v=$(opt db_username); [ -n "${v}" ] && export SPOOLMAN_DB_USERNAME="${v}"
    v=$(opt db_password); [ -n "${v}" ] && export SPOOLMAN_DB_PASSWORD="${v}"
    v=$(opt api_token); [ -n "${v}" ] && export SPOOLMAN_API_TOKEN="${v}"
fi

# Persist Spoolman's data (and the default SQLite database) in the add-on's /data volume, owned by
# the unprivileged app user the image runs as.
export SPOOLMAN_DIR_DATA=/data
mkdir -p /data
chown -R 1000:1000 /data 2>/dev/null || true

exec /home/app/spoolman/entrypoint.sh
