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

The catalog submission itself is tracked in
[#337](https://github.com/sherrmann/Spoolman-NG/issues/337).
