# Spoolman NG — Home Assistant add-on repository

> ⚠️ **Experimental.** This Home Assistant Supervisor add-on packaging (issue #89) has **not** been
> exercised against a live Supervisor. It follows the documented add-on conventions and reuses the
> published multi-arch image, but treat it as a starting point and please report problems.

This directory is a [Home Assistant add-on repository](https://developers.home-assistant.io/docs/add-ons/repository).
It lets Home Assistant OS / Supervisor users run the Spoolman NG **server** itself as an add-on,
without a separate Docker host.

> This is different from the third-party [HACS integration](https://github.com/Disane87/spoolman-homeassistant),
> which *connects* Home Assistant to an existing Spoolman instance. This add-on *runs* Spoolman.

## Installing

1. In Home Assistant, go to **Settings → Add-ons → Add-on Store**.
2. From the ⋮ menu, choose **Repositories**, and add:
   `https://github.com/sherrmann/Spoolman-NG`
3. The **Spoolman NG** add-on appears under this repository — install it, then start it.
4. Open the web UI on port `8000` of your Home Assistant host.

The add-on builds from the published `ghcr.io/sherrmann/spoolman` image and stores its data
(including the default SQLite database) in the add-on's persistent `/data` volume, so it survives
restarts and updates. See the add-on's **Documentation** tab (`spoolman/DOCS.md`) for configuration
options, including pointing it at an external PostgreSQL/MariaDB/CockroachDB.
