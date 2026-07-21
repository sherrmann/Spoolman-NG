# BigBear app catalogs

[BigBearTechWorld](https://github.com/bigbeartechworld) maintains community app
catalogs (BigBearUniversal Apps, big-bear-casaos for CasaOS/ZimaOS) whose
entries are plain docker-compose files. Upstream Spoolman is already listed
there ([announcement thread](https://community.bigbeartechworld.com/t/added-spoolman-to-bigbearuniversal-apps/5108));
[`docker-compose.yml`](docker-compose.yml) in this directory is the
Spoolman NG entry, pre-adapted to their conventions:

- `big-bear-spoolman-ng` naming for the stack, service, and container, and a
  `/DATA/AppData/big-bear-spoolman-ng/...` data volume (the CasaOS appdata
  layout their catalogs use).
- Otherwise identical to the canonical compose example in the
  [installation guide](../../docs/installation.md#docker-recommended-the-only-supported-option-on-windowsmacos):
  `ghcr.io/sherrmann/spoolman-ng:latest`, host port 7912 → container 8000,
  data (SQLite + backups) under `/home/app/.local/share/spoolman`.

The file also works stand-alone on any Docker host (`docker compose up -d`) —
adjust the volume's host path if you're not on a `/DATA/AppData` system.

## Submitting (maintainers)

BigBear takes catalog additions as community submissions — via their
[community](https://community.bigbeartechworld.com/) (now bridged to Discord)
or a pull request against the relevant catalog repository, using this compose
file as the entry. Catalog metadata beyond the compose file (description,
icon, screenshots) can be lifted from the repository README; a 512×512 icon is
served at
`https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/client/public/pwa-512x512.png`.

Since upstream Spoolman already has an entry, an alternative to a new entry is
proposing an NG variant alongside it — the only functional difference is the
image (`ghcr.io/sherrmann/spoolman-ng`), everything else (port, volume target,
env vars) is drop-in identical, and an existing upstream data directory is
migrated automatically on first start.
