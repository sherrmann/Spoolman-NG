# Security Policy

## Supported versions

Only the latest release of Spoolman NG receives security fixes. Spoolman NG
forked from Donkie/Spoolman at v0.23.1, so nothing at or below that point is
covered by either project — upgrade to a current Spoolman NG release to receive
fixes from us. Upstream resumed active development in July 2026 and issues its
own advisories; if you run upstream Spoolman rather than Spoolman NG, report
there instead.

## Threat model

By default Spoolman NG has no authentication or authorisation. It is designed to
run on a trusted home/LAN network next to Klipper/Moonraker/OctoPrint, and the
entire REST API — including endpoints that create data and write physical NFC
tags — is open to anyone who can reach the port. Authentication is opt-in: a
single shared bearer token (`SPOOLMAN_API_TOKEN`) or per-user accounts with
administrator and read-only roles (see
[Security & exposure](README.md#security--exposure)). Either way `/metrics` and
the static web assets stay unauthenticated. Exposing an instance directly to the
internet is not a supported configuration; see the README for recommended
reverse-proxy/VPN setups.

Two guards, independent of whatever authentication is configured:

* **Origin guard, on by default.** Every `POST`, `PUT`, `PATCH` and `DELETE`, and every
  websocket handshake, is refused unless its `Origin` is the instance's own or
  is listed in `SPOOLMAN_CORS_ORIGIN` — HTTP 403 for a request, and for a
  handshake a close before it is accepted, so no data is ever sent. Non-browser
  clients such as Moonraker, OctoPrint and curl send no `Origin` header at all
  and are unaffected.
* **Host guard, opt-in.** Set `SPOOLMAN_ALLOWED_HOSTS` and any request addressed
  to some other hostname is refused, which is what closes DNS rebinding. It is
  opt-in because the only names it can refuse are registrable public domains, so
  defaulting it on would break the reverse-proxy deployments that configure
  nothing today, while the deployments rebinding can actually reach are
  addressed by IP literals, single-label names and `.local` — which it never
  refuses anyway.

`SPOOLMAN_CORS_ORIGIN=*`, and likewise `SPOOLMAN_DEBUG_MODE=TRUE`, is taken as
the operator opting out: both guards are disabled, and CORS then refuses to
allow credentials. With a wildcard and credentials both allowed, Starlette would
echo the caller's origin back and tell the browser it may send cookies to
whichever site asked — harmless to Spoolman itself, which sets no cookies, but
not to a reverse proxy in front of it that authenticates with one.

**Bearer tokens and CSRF.** Spoolman NG's credential is an `Authorization`
header, never a cookie, and nothing a foreign page can reach for — a form post,
the browser websocket API, a simple `fetch` — can attach it. Credential-riding
CSRF therefore does not apply to an instance that has a token or accounts
configured. The guards above matter most on the default no-auth deployment,
where being able to reach the port is the whole of the authority.

**The websocket `?token=` parameter.** A browser cannot set a header on a
websocket handshake, so both web clients pass the credential as `?token=` on the
websocket URL. The origin guard changes what a foreign page can *do* with that,
not what the token exposes: a cross-origin page never could read the token out
of another origin's storage, and it now cannot even open the handshake;
same-origin script could always read it, and still can. What is left is passive
exposure in logs. Spoolman replaces the value with `[redacted]` in its own
console output and in `spoolman.log`, but a reverse proxy's access log will
still contain it unless the proxy is configured not to log query strings, and
anything that sees the request line before TLS terminates sees it too. It is
never written to the database. The query parameter is kept deliberately: it is
the only way a browser can authenticate a websocket.

Reports that assume an attacker who can already reach the API (e.g. "an
unauthenticated user can create spools") therefore describe intended behaviour,
not a vulnerability. In scope are, for example: bugs that let a crafted request
escape the API's data model (SQL injection, path traversal, SSRF via
`EXTERNAL_DB_URL`/3DFP fetching), a way past either guard above (a cross-origin
write or websocket the origin guard accepts, a rebound hostname the host guard
allows), cross-site attacks against the web client (XSS), denial of service
through malformed input (e.g. crafted NFC tag payloads), and vulnerabilities in
the published Docker images.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Instead, report
privately via
[GitHub Security Advisories](https://github.com/sherrmann/Spoolman-NG/security/advisories/new).

Include the version (or image tag), reproduction steps, and impact. You should
receive an initial response within 14 days. Fixes are published as a regular
release, credited to the reporter unless anonymity is requested.
