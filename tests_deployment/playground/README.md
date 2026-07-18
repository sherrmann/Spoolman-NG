# Moonraker + Spoolman NG playground (virtual printer)

An interactive stack for trying the Klipper/Moonraker ↔ Spoolman NG integration with
no printer hardware: [prind](https://github.com/mkuf/prind) (Klipper in docker) with a
**simulavr-emulated MCU**, Mainsail as the UI, and Spoolman NG behind the same traefik
under a sub-path (which exercises `SPOOLMAN_BASE_PATH` for real). Also the seed of the
planned virtual-printer e2e tests (#277).

```bash
tests_deployment/playground/up.sh        # first run builds the MCU image (a few minutes)
tests_deployment/playground/down.sh      # stop; add -v to wipe volumes (Spoolman DB, gcode)
```

| What | Where |
|---|---|
| Mainsail (printer UI) | <http://localhost:8010/> |
| Spoolman NG | <http://localhost:8010/spoolman/> |
| Moonraker API | `http://localhost:8010/server/…` (e.g. `/server/spoolman/status`) |

`SPOOLMAN_NG_TAG=<tag> up.sh` pins the server image (default `latest`).

## Things to try

1. **Create a filament + spool** in Spoolman (<http://localhost:8010/spoolman/>).
2. **Select it as the active spool** in Mainsail — the Spoolman panel appears because
   Moonraker's `[spoolman]` component is enabled (up.sh uncomments it in
   `tests_deployment/.cache/prind/config/moonraker.conf`, pointing at
   `http://traefik/spoolman`).
3. **Run a "print"**: upload any small gcode in Mainsail and start it — the virtual MCU
   executes it, and Moonraker reports the consumed filament to Spoolman
   (`PUT /api/v1/spool/{id}/use`); watch the spool's remaining weight drop.
4. **Kill Spoolman** (`docker stop spoolman-playground-spoolman-1`) and watch Moonraker
   flag it unavailable (`/server/spoolman/status`), then start it again — the WS
   reconnect is the availability mechanism the audit verified.

## Notes

- The prind checkout lives in `tests_deployment/.cache/prind` (gitignored); up.sh
  clones and patches it idempotently. The stack runs under the compose project name
  `spoolman-playground`, so it never collides with other compose apps.
- prind ships its own `spoolman` profile pinned to upstream's image — the
  `spoolman-ng.yaml` overlay swaps in `ghcr.io/sherrmann/spoolman-ng` (one more
  catalog where NG is a drop-in, see #266).
- The Moonraker **update manager** path (`[update_manager Spoolman]`, type `zip`) is a
  *native-install* concern and is covered by `tests_deployment/run.sh moonraker`, not
  this containerized stack — in Docker, updates arrive by pulling a new image.
