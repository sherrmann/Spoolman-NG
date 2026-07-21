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

## Using the template before it's in Community Apps

Unraid reads user templates from the flash share. Copy the XML there and it
appears in the template dropdown:

```bash
# from any machine that can reach the Unraid share, or via the flash share in SMB
curl -fsSL https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/integrations/unraid/spoolman-ng.xml \
  -o /boot/config/plugins/dockerMan/templates-user/spoolman-ng.xml
```

Then **Docker → Add Container** and pick `Spoolman-NG` under *Select a
template*.

## Community Apps listing (maintainers)

Community Applications (CA) indexes templates from **registered template
repositories**. Getting listed is a one-time manual step by a template
maintainer:

1. Keep the template in a GitHub repository CA can scan (this file is the
   source of truth; CA scanning conventions may require mirroring it into a
   dedicated `unraid-templates` repository).
2. Request inclusion in the CA appfeed via the Unraid forums' template
   repository submission process (the *Community Applications* support thread
   points at the current procedure), providing the repository URL.
3. After acceptance, CA picks up template changes from the repository
   automatically; `<TemplateURL>` keeps installs self-updating.

Once listed, installing becomes: **Apps** tab → search "Spoolman NG" → Install.
