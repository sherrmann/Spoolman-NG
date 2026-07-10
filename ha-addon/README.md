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

Supervisor only accepts add-on repositories whose manifest sits at the **root** of the git
repository, so the main Spoolman-NG repo URL cannot be added directly while this packaging lives
under `ha-addon/`. Install it as a **local add-on** instead:

1. Enable the Samba or SSH add-on so you can reach your Home Assistant `/addons` share.
2. Copy the `ha-addon/spoolman` directory from this repository into `/addons/spoolman_ng` on the
   Home Assistant host.
3. In Home Assistant, go to **Settings → Add-ons → Add-on Store**, open the ⋮ menu and pick
   **Check for updates** — the **Spoolman NG** add-on appears under *Local add-ons*.
4. Install and start it, then open the web UI on port `8000` of your Home Assistant host.

(If demand justifies it, a dedicated add-on repository with the manifest at its root can be split
out so the usual add-a-repository-URL flow works; see issue #89.)

The add-on builds from the published `ghcr.io/sherrmann/spoolman-ng` image and stores its data
(including the default SQLite database) in the add-on's persistent `/data` volume, so it survives
restarts and updates. See the add-on's **Documentation** tab (`spoolman/DOCS.md`) for configuration
options, including pointing it at an external PostgreSQL/MariaDB/CockroachDB.
