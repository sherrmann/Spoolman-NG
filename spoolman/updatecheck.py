"""Background check for a newer Spoolman-NG release (#293).

Docker users on ``:latest`` and native installs otherwise drift silently: the server
knows its own version but nothing tells the user a newer release exists. Once a day this
module asks GitHub for the latest published release and caches the result so
``GET /api/v1/info`` can additively report ``latest_version`` / ``update_available`` to
the UI.

Privacy: the *only* outbound call this makes is a single request to
``api.github.com`` (no telemetry, no payload about the install is sent). Conditional
requests (ETag) keep it gentle on GitHub's rate limits. Disable it entirely with
``SPOOLMAN_UPDATE_CHECK=FALSE``.

The version-comparison and parsing logic mirrors the mobile companion's
``mobile/src/lib/update.ts`` so both surfaces agree on what "newer" means.
"""

import asyncio
import datetime
import logging
import re
from dataclasses import dataclass, field

import httpx
from scheduler.asyncio.scheduler import Scheduler

from spoolman import env

logger = logging.getLogger(__name__)

#: owner/repo whose GitHub releases we track.
GITHUB_REPO = "sherrmann/Spoolman-NG"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

#: One check a day is plenty - releases are cut at most daily and the value only feeds a
#: passive "update available" badge.
CHECK_INTERVAL = datetime.timedelta(days=1)

_REQUEST_TIMEOUT = 10.0


@dataclass
class UpdateStatus:
    """The cached result of the most recent update check.

    Exposed additively on ``/info``; every field is safe to serialise as-is.
    """

    #: Newest release tag, normalised without a leading "v" (e.g. "2026.7.14"). None until
    #: a check has succeeded, or when the check is disabled/failing.
    latest_version: str | None = None
    #: True when ``latest_version`` is strictly newer than the running version.
    update_available: bool = False
    #: GitHub release page for the latest release, for "view release notes" links.
    release_url: str | None = None


@dataclass
class _CheckState:
    """Mutable cache shared by the background check and the /info reader.

    We mutate this instance in place (never rebind the module name) so both sides see one
    object without any ``global`` juggling. The scheduler drives ``_check`` serially on the
    event loop and ``/info`` only reads ``status``, so no lock is needed.
    """

    #: Result of the most recent successful check.
    status: UpdateStatus = field(default_factory=UpdateStatus)
    #: Last ETag GitHub returned, replayed as If-None-Match so an unchanged release costs a
    #: cheap 304 instead of a full body. In-memory only - a restart just re-fetches once.
    etag: str | None = None


_state = _CheckState()


def _normalize_version(value: str) -> str:
    """Strip a single leading "v"/"V" so "v2026.7.8" and "2026.7.8" compare equal."""
    return re.sub(r"^[vV]", "", value.strip())


def _parse_version(value: str) -> list[int]:
    """Split a dotted version into numeric components, ignoring any pre-release suffix.

    "2026.7.8" -> [2026, 7, 8]; non-numeric parts become 0. Mirrors the mobile logic.
    """
    parts = re.split(r"[.+-]", _normalize_version(value))
    return [int(part) if part.isdigit() else 0 for part in parts]


def _compare_versions(a: str, b: str) -> int:
    """Return -1 if a < b, 0 if equal, 1 if a > b - component-wise, zero-padded."""
    pa = _parse_version(a)
    pb = _parse_version(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


def is_update_available(current_version: str, latest_tag: str) -> bool:
    """Return True when latest_tag is a strictly newer version than the running one."""
    return _compare_versions(latest_tag, current_version) > 0


def get_status() -> UpdateStatus:
    """Return the most recent cached update status (never triggers a network call)."""
    return _state.status


def _parse_latest_release(payload: object) -> tuple[str, str] | None:
    """Pull ``(tag, html_url)`` out of the GitHub /releases/latest payload, or None.

    Returns None when the payload is malformed or has no tag - the mirror of the mobile
    ``parseLatestRelease`` (we don't need the APK asset here, only the tag and page).
    """
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag:
        return None
    html_url = payload.get("html_url")
    return tag, html_url if isinstance(html_url, str) else ""


async def _check() -> None:
    """Fetch the latest release and refresh the cached status. Never raises.

    Uses a conditional request: on an unchanged release GitHub answers 304 and the cache
    is left as-is. Any failure (network, non-2xx, malformed body) is logged and leaves the
    previous status untouched rather than clearing a good value.
    """
    current_version = env.get_version()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _state.etag:
        headers["If-None-Match"] = _state.etag

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.get(LATEST_RELEASE_URL, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Update check failed to reach GitHub: %s", exc)
        return

    if response.status_code == httpx.codes.NOT_MODIFIED:
        logger.debug("Update check: latest release unchanged since last check (304).")
        return
    if response.status_code != httpx.codes.OK:
        logger.warning("Update check got unexpected status %d from GitHub.", response.status_code)
        return

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Update check could not parse GitHub response as JSON.")
        return

    parsed = _parse_latest_release(payload)
    if parsed is None:
        logger.warning("Update check received a release payload without a tag.")
        return

    tag, html_url = parsed
    _state.etag = response.headers.get("ETag")

    latest_version = _normalize_version(tag)
    available = is_update_available(current_version, tag)
    _state.status = UpdateStatus(
        latest_version=latest_version,
        update_available=available,
        release_url=html_url or None,
    )
    if available:
        logger.info("A newer Spoolman-NG release is available: %s (running %s).", latest_version, current_version)
    else:
        logger.debug("Update check: running the latest release (%s).", current_version)


def schedule_tasks(scheduler: Scheduler) -> None:
    """Schedule the daily update check on the provided scheduler.

    No-op when disabled via ``SPOOLMAN_UPDATE_CHECK=FALSE``, so a privacy-conscious
    deployment makes zero outbound calls.

    Args:
        scheduler: The scheduler to use for scheduling tasks.

    """
    if not env.is_update_check_enabled():
        logger.info("Update check disabled (SPOOLMAN_UPDATE_CHECK). Skipping release check.")
        return

    logger.info("Scheduling daily update check against %s.", GITHUB_REPO)

    # Run once shortly after startup, then daily. A tiny delay keeps the network call off
    # the critical startup path (the scheduler still owns the coroutine, so it's awaited).
    scheduler.once(datetime.timedelta(seconds=5), _check)  # type: ignore[arg-type]
    scheduler.cyclic(CHECK_INTERVAL, _check)  # type: ignore[arg-type]


async def check_now() -> UpdateStatus:
    """Run a check immediately and return the resulting status (used by tests/manual runs)."""
    await _check()
    return get_status()


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    print(asyncio.run(check_now()))  # noqa: T201
