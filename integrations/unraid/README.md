# Unraid template

[`spoolman-ng.xml`](spoolman-ng.xml) is a Docker container template for
[Unraid](https://unraid.net/)'s Docker manager, referencing
`ghcr.io/sherrmann/spoolman-ng:latest`. Defaults it configures:

| Setting | Default | Notes |
|---|---|---|
| Web UI port | host **7912** → container 8000 | Same convention as the compose example; the WebUI button uses it. |
| Data directory | `/mnt/user/appdata/spoolman-ng` → `/home/app/.local/share/spoolman` | SQLite database + automatic nightly backups. |
| `TZ` | `UTC` | Timestamps in the UI/API. |
| `PUID` / `PGID` | `99` / `100` | Unraid's `nobody:users`, so the appdata share stays accessible; the container chowns the data directory itself on start. |

Anything else (external databases, API token, metrics, …) is a plain
`SPOOLMAN_*` environment variable added via *Add another Path, Port, Variable* —
see the [environment reference](../../docs/installation.md#environment-variable-reference).
For a server-side USB NFC reader, add `--device=/dev/bus/usb` under *Extra
Parameters* and set `SPOOLMAN_NFC_ENABLED=TRUE` ([NFC guide](../../docs/nfc.md)).

**Migrating from the upstream Spoolman template**: stop the old container,
copy its appdata directory to `/mnt/user/appdata/spoolman-ng` (or point this
template's data path at the existing directory), start — the schema migrates
automatically on first start. Back up the directory first.

## Installing the template

A Community Apps listing (install from the **Apps** tab) is tracked in
[#336](https://github.com/sherrmann/Spoolman-NG/issues/336). Until then, the
template installs manually: Unraid reads user templates from the flash share,
so copy the XML there and it appears in the template dropdown:

```bash
# from any machine that can reach the Unraid share, or via the flash share in SMB
curl -fsSL https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/integrations/unraid/spoolman-ng.xml \
  -o /boot/config/plugins/dockerMan/templates-user/spoolman-ng.xml
```

Then **Docker → Add Container** and pick `Spoolman-NG` under *Select a
template*. `<TemplateURL>` points at the raw XML on `master`, so installed
containers keep picking up template fixes.
