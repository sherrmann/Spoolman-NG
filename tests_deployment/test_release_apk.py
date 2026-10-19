"""Release-asset contract for the Android companion APK (#302).

The release workflow attaches `spoolman-companion-<tag>.apk` (mobile-apk.yml names it after
the git ref, so the filename carries the tag verbatim) and stamps the tag's version into the
app. Asserts the published APK's filename, manifest `versionName` and `versionCode` agree
with the release. Skips for older releases that predate the APK, and for v2026.7.6 to v2026.7.8,
which attached an APK whose manifest still carried the placeholder version 0.1.0 (code 1).
"""

from __future__ import annotations

import re
import struct
import zipfile
from typing import TYPE_CHECKING

import pytest

from tests_deployment.conftest import REPO
from tests_deployment.helpers import download, github_json

if TYPE_CHECKING:
    from pathlib import Path

    from tests_deployment.conftest import Release

APK_NAME_RE = re.compile(r"^spoolman-companion-(?P<version>.+)\.apk$")

# AXML (Android binary XML) constants; see AOSP frameworks/base ResourceTypes.h.
_RES_STRING_POOL = 0x0001
_RES_XML_START_ELEMENT = 0x0102
_UTF8_FLAG = 0x100
_NO_ENTRY = 0xFFFFFFFF
_TYPE_STRING = 0x03
_TYPE_INT_DEC = 0x10
_TYPE_INT_HEX = 0x11


def _read_string(data: bytes, pos: int, *, utf8: bool) -> str:
    """Decode one length-prefixed string-pool entry starting at ``pos``."""
    if utf8:
        # Two length prefixes (UTF-16 char count, then byte count); each is 1 byte, or 2 when
        # the high bit of the first is set.
        pos += 2 if data[pos] & 0x80 else 1
        length = data[pos]
        pos += 1
        if length & 0x80:
            length = ((length & 0x7F) << 8) | data[pos]
            pos += 1
        return data[pos : pos + length].decode("utf-8", errors="replace")
    (length,) = struct.unpack_from("<H", data, pos)
    pos += 2
    if length & 0x8000:
        (low,) = struct.unpack_from("<H", data, pos)
        length = ((length & 0x7FFF) << 16) | low
        pos += 2
    return data[pos : pos + length * 2].decode("utf-16-le", errors="replace")


def _parse_string_pool(data: bytes, chunk: int) -> list[str]:
    """Read every string of the string-pool chunk that starts at offset ``chunk``."""
    string_count, _style_count, flags, strings_start = struct.unpack_from("<IIII", data, chunk + 8)
    offsets = struct.unpack_from(f"<{string_count}I", data, chunk + 28)
    base = chunk + strings_start
    return [_read_string(data, base + off, utf8=bool(flags & _UTF8_FLAG)) for off in offsets]


def read_manifest_attributes(axml: bytes) -> dict[str, str | int]:
    """Return the attributes of the root ``<manifest>`` element of a binary AndroidManifest.xml.

    Layout: an XML header chunk wrapping a sequence of chunks, each led by
    (type u16, header size u16, size u32). We need the string pool (attribute and element names,
    string values) and the first start-element chunk (the manifest). Integers (versionCode) come
    back as ``int``; strings (versionName) are resolved through the pool.
    """
    strings: list[str] = []
    pos = 8  # skip the file header (type, header size, total size)
    while pos + 8 <= len(axml):
        chunk_type, _header_size, size = struct.unpack_from("<HHI", axml, pos)
        if chunk_type == _RES_STRING_POOL:
            strings = _parse_string_pool(axml, pos)
        elif chunk_type == _RES_XML_START_ELEMENT:
            # Chunk header (16 bytes), then ns, name, attrStart, attrSize, attrCount (+ 3 index u16s).
            _ns, name, attr_start, attr_size, attr_count = struct.unpack_from("<IIHHH", axml, pos + 16)
            if strings[name] != "manifest":
                raise ValueError(f"first element is {strings[name]!r}, expected 'manifest'")
            attrs: dict[str, str | int] = {}
            for i in range(attr_count):
                # Each attribute: ns, name, raw value (string index or none), then a typed value.
                a_off = pos + 16 + attr_start + i * attr_size
                _ans, a_name, raw, _vsize, _res0, data_type, value = struct.unpack_from("<IIIHBBI", axml, a_off)
                if raw != _NO_ENTRY:
                    attrs[strings[a_name]] = strings[raw]
                elif data_type == _TYPE_STRING:
                    attrs[strings[a_name]] = strings[value]
                elif data_type in (_TYPE_INT_DEC, _TYPE_INT_HEX):
                    attrs[strings[a_name]] = value
            return attrs
        if size < 8:
            raise ValueError(f"corrupt AXML chunk of size {size} at offset {pos}")
        pos += size
    raise ValueError("no <manifest> element found in AXML")


@pytest.fixture(scope="module")
def apk(release: Release, cache_dir: Path) -> tuple[str, Path]:
    """Name and cached path of the release's companion APK; skips when there is none."""
    if release.local:
        pytest.skip("local zip under test — the APK is a GitHub release asset")
    meta = github_json(f"repos/{REPO}/releases/tags/{release.tag}")
    assets = [a for a in meta["assets"] if APK_NAME_RE.match(a["name"])]
    if not assets:
        pytest.skip(f"release {release.tag} has no spoolman-companion-*.apk asset (predates the Android app)")
    asset = assets[0]
    path = cache_dir / "releases" / release.tag / asset["name"]
    if not path.exists():
        download(asset["browser_download_url"], path)
    return asset["name"], path


def _bare(version: str) -> str:
    return version.removeprefix("v")


def _manifest(path: Path) -> dict[str, str | int]:
    with zipfile.ZipFile(path) as zf:
        return read_manifest_attributes(zf.read("AndroidManifest.xml"))


def test_apk_filename_carries_the_release_tag(release: Release, apk: tuple[str, Path]) -> None:
    name, _ = apk
    match = APK_NAME_RE.match(name)
    assert match is not None
    assert _bare(match["version"]) == _bare(release.tag), (
        f"APK {name!r} does not match release tag {release.tag!r} — Obtainium and the in-app updater "
        "compare the asset name against the tag."
    )


#: What the Android project's manifest said before CI stamped the release version into it.
_UNSTAMPED = ("0.1.0", 1)
#: The releases that shipped such an APK. Only these are excused: a later release with an
#: unstamped APK is the updater regression this test exists to catch.
_UNSTAMPED_RELEASES = frozenset({"v2026.7.6", "v2026.7.7", "v2026.7.8"})


def test_apk_manifest_version_name_equals_the_tag(release: Release, apk: tuple[str, Path]) -> None:
    _, path = apk
    manifest = _manifest(path)
    version_name = manifest.get("versionName")
    if release.tag in _UNSTAMPED_RELEASES and (version_name, manifest.get("versionCode")) == _UNSTAMPED:
        pytest.skip(f"{release.tag} predates version stamping: its APK still says 0.1.0 (code 1)")
    assert version_name == _bare(release.tag), (
        f"manifest versionName {version_name!r} != release tag {release.tag!r} — the in-app updater "
        "would offer an update to the version it is already running (or never stop offering it)."
    )


def test_apk_manifest_version_code_is_a_positive_integer(apk: tuple[str, Path]) -> None:
    _, path = apk
    version_code = _manifest(path).get("versionCode")
    assert isinstance(version_code, int), f"versionCode is not an integer: {version_code!r}"
    assert version_code > 0, f"Android needs a positive versionCode to sideload over an older build, got {version_code}"


def test_axml_reader_resolves_both_attribute_kinds(apk: tuple[str, Path]) -> None:
    """Pin the reader itself: the manifest root declares a package plus the stamped version pair."""
    _, path = apk
    attrs = _manifest(path)
    assert isinstance(attrs.get("package"), str)
    assert isinstance(attrs.get("versionName"), str)
    assert isinstance(attrs.get("versionCode"), int)
