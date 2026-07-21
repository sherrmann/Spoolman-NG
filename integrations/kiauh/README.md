# KIAUH v6 community extension

[KIAUH](https://github.com/dw-0/kiauh) (Klipper Installation And Update Helper)
is the standard way many Klipper users install their stack. KIAUH v5 shipped a
built-in Spoolman installer; v6 replaced built-ins with **community-maintained
extensions** ([dw-0/kiauh#569](https://github.com/dw-0/kiauh/issues/569)). This
directory is the Spoolman NG extension for that system.

What it gives you, from KIAUH's `[E]xtensions` menu:

- **Install** — downloads the latest `spoolman.zip` release, extracts it to
  `~/Spoolman`, lets you pick the port, and runs the bundled
  `scripts/install.sh` (uv + Python environment + `Spoolman` systemd service).
  It then offers to wire Moonraker: the documented
  `[update_manager Spoolman]` *type: zip* recipe for one-click updates from
  Mainsail/Fluidd, the `[spoolman]` section for Klipper filament tracking, and
  the `Spoolman` entry in `moonraker.asvc` so Moonraker may restart the
  service.
- **Update** — runs `scripts/update.sh` (in-place update that preserves
  `.env`, `.venv` and the local `uv/` toolchain). With the Moonraker
  integration set up, updates also appear directly in your printer UI.
- **Remove** — removes the systemd service, the Moonraker integration and the
  install directory. Your database (`~/.local/share/spoolman`) is kept unless
  you explicitly delete it in the last step.

## Installing the extension into KIAUH

KIAUH v6 discovers extensions dropped into its `kiauh/extensions/` folder.
One line installs (or refreshes) the extension into `~/kiauh`:

```bash
curl -fsSL https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/integrations/kiauh/install-extension.sh | bash
```

KIAUH cloned somewhere else? Pass the path:

```bash
curl -fsSL https://raw.githubusercontent.com/sherrmann/Spoolman-NG/master/integrations/kiauh/install-extension.sh | bash -s -- /path/to/kiauh
```

(From a Spoolman-NG checkout, `bash integrations/kiauh/install-extension.sh`
does the same with the local files.) Then start KIAUH as usual (`./kiauh.sh`,
or `kiauh` if installed via its setup) and pick **[E]xtensions → Spoolman NG
(native install)**.

To uninstall the extension itself (not Spoolman NG), delete the folder:

```bash
rm -rf ~/kiauh/kiauh/extensions/spoolman_ng
```

## Notes

- KIAUH identifies extensions by the `index` in `metadata.json` and skips
  duplicates. This extension uses **30**, well clear of the built-ins (1–16 as
  of KIAUH v6.1). If a future KIAUH release or another community extension
  claims 30, KIAUH prints a duplicate-index warning — edit `metadata.json` and
  pick any free number.
- The extension installs the same layout as the documented
  [native install](../../docs/installation.md#native-install-linux), so
  everything in that guide (`.env` reference, backups, NFC extra, migration
  notes) applies unchanged. An install made by hand can be adopted by the
  extension and vice versa — both use `~/Spoolman` and the `Spoolman` service.
- KIAUH is GPL-3.0 and the extension files run inside it; the copies in this
  repository are covered by this repository's MIT license.
