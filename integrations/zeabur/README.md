# Zeabur templates

[Zeabur](https://zeabur.com) is a hosting platform with one-click template
deploys. Upstream Spoolman has a community template there; these files are the
Spoolman NG equivalents, kept in-repo so the published templates can be
reviewed and updated like any other code:

- [`template.yaml`](template.yaml) — **SQLite (default)**: one service, the
  bundled SQLite database on a persistent volume mounted at
  `/home/app/.local/share/spoolman`. The right choice for almost everyone.
- [`template-postgres.yaml`](template-postgres.yaml) — **PostgreSQL variant**:
  adds a `postgres:17` service (own volume, generated password) and wires
  `SPOOLMAN_DB_*` to it automatically.

Both deploy `ghcr.io/sherrmann/spoolman-ng:latest` serving HTTP on container
port 8000, and ask for a domain during deploy. Everything else is standard
Spoolman NG — the full `SPOOLMAN_*` reference in the
[installation guide](../../docs/installation.md#environment-variable-reference)
applies; add variables to the service on Zeabur as needed (for instance
`SPOOLMAN_API_TOKEN` before exposing the instance beyond yourself — see
[Security & exposure](../../README.md#security--exposure)).

## Deploying a template yourself

You don't need the marketplace listing — the YAML deploys straight into your
own Zeabur account:

```bash
npx zeabur@latest template deploy -f template.yaml
```

(Log in when the CLI asks, pick a project/region, done. Use
`-f template-postgres.yaml` for the PostgreSQL variant.)

## Marketplace listing

Publishing these templates to the Zeabur marketplace (one-click from
`zeabur.com/templates`, like upstream's) is tracked in
[#335](https://github.com/sherrmann/Spoolman-NG/issues/335). Template updates
never touch already-deployed projects, and the image tag is `latest` — so a
plain service restart on Zeabur pulls the newest release regardless of how the
template was deployed.

## Upgrades & data

The SQLite database lives on the template's volume and survives redeploys;
schema migrations run automatically on startup, so upgrading is just
redeploying (or restarting) the service. Take a backup first for easy
rollback — nightly automatic SQLite backups are on by default, written to
`backups/` inside the same volume.
