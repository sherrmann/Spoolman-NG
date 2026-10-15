# Monitoring with Prometheus

Spoolman NG can expose its inventory as Prometheus metrics, letting you graph
filament usage over time (e.g. in Grafana) and alert on low stock.

## Enable metrics

Set the environment variable and restart:

```
SPOOLMAN_METRICS_ENABLED=TRUE
```

Metrics are then served at `http://<host>:<port>/metrics` (honoring
`SPOOLMAN_BASE_PATH` if set). Spool and filament gauges refresh from the
database once per minute.

> The metrics endpoint is **always unauthenticated — deliberately, even when API
> auth (`SPOOLMAN_API_TOKEN` / user accounts) is enabled** (#232): Prometheus
> scrapers conventionally run without credentials, so `/metrics` is served
> outside the auth middleware. The gauges include your inventory and prices —
> keep the port on a trusted network, or restrict `/metrics` at your reverse
> proxy (e.g. an nginx `location = /metrics` block allowing only the Prometheus
> host) if the API is otherwise exposed with auth. The server logs a reminder at
> startup when both metrics and auth are enabled.

## Exported metrics

| Metric | Labels | Meaning |
|---|---|---|
| `spoolman_spool_price` | `spool_id`, `filament_id` | Total price of the spool. |
| `spoolman_spool_weight_used` | `spool_id`, `filament_id` | Used weight in grams (monotonically increases as you print). |
| `spoolman_spool_initial_weight` | `spool_id`, `filament_id` | Net filament weight of the full spool in grams. |
| `spoolman_filament_info` | `filament_id`, `vendor`, `name`, `material`, `color` | Filament metadata carrier (value is always 1; join on `filament_id`). |
| `spoolman_filament_density` | `filament_id` | Density in g/cm³. |
| `spoolman_filament_diameter` | `filament_id` | Diameter in mm. |
| `spoolman_filament_weight` | `filament_id` | Net weight of a full spool of this filament in grams. |
| `spoolman_build_info` | version fields | Build/version information. |

## Scrape configuration

```yaml
scrape_configs:
  - job_name: spoolman
    scrape_interval: 60s # gauges refresh every minute; scraping faster adds nothing
    static_configs:
      - targets: ["spoolman-host:7912"]
    # metrics_path: /spoolman/metrics   # if you run with SPOOLMAN_BASE_PATH=/spoolman
```

## Useful queries

Remaining weight per spool (grams):

```promql
spoolman_spool_initial_weight - spoolman_spool_weight_used
```

Filament consumed in the last 7 days, per spool:

```promql
increase(spoolman_spool_weight_used[7d])
```

Total consumption per material (joins usage to filament metadata):

```promql
sum by (material) (
  increase(spoolman_spool_weight_used[30d])
  * on (filament_id) group_left(material) spoolman_filament_info
)
```

Low-stock alert (below 15% remaining):

```promql
(spoolman_spool_initial_weight - spoolman_spool_weight_used)
  / spoolman_spool_initial_weight < 0.15
```

Note that gauges only exist for spools present in the database; archived or
deleted spools stop being exported, so use `increase()`/`rate()` windows rather
than raw counters when aggregating history.

## Request timing

Two optional settings show where the time goes when a page feels slow. Both are
off by default and add nothing to requests while off.

- `SPOOLMAN_SERVER_TIMING=TRUE` adds a `Server-Timing: app;dur=12.3, db;dur=4.5`
  header to responses, in milliseconds: `app` is the time until the response
  starts, `db` the part of it spent in SQL. Browsers show it in the developer
  tools' Network tab. It is never sent on 401 or 403 responses or for anything
  under `/api/v1/auth/`, because an exact time on a failed login would reveal
  which usernames exist.
- `SPOOLMAN_SLOW_REQUEST_MS=500` logs a warning for each request that takes at
  least that many milliseconds to start responding, with the method, path
  (without the query string), status, total and database time and the number of
  queries. `0` logs every request. Streams (AI chat, MCP) are not logged.

The clock stops when the response starts, so sending a large body to a slow
client is not included.
