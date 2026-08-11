# -*- coding: utf-8 -*-
"""Pure-Python helpers for comparing the packaged app with GitHub releases.

This module intentionally performs no network or GUI work.  Callers fetch the
GitHub response themselves, pass it to :func:`parse_latest_release_payload`,
then compare the returned version with :data:`CURRENT_VERSION`.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, TypeAlias


CURRENT_VERSION: Final = "4.1.0"
LATEST_RELEASE_URL: Final = (
    "https://github.com/AustinHongLee/NavisWorks_Line_flow_Tools/releases/latest"
)
RELEASE_TAG_URL_PREFIX: Final = (
    "https://github.com/AustinHongLee/NavisWorks_Line_flow_Tools/releases/tag/"
)
EXPECTED_EXE_NAME: Final = "NavisWorks_Line_flow_Tools.exe"

VersionTuple: TypeAlias = tuple[int, int, int]
VersionKind: TypeAlias = Literal[
    "current",
    "ahead",
    "update_major",
    "update_minor",
    "update_patch",
    "invalid",
]

VERSION_KIND_LABELS: Final[dict[str, str]] = {
    "current": "已是最新版",
    "ahead": "本機版本較新",
    "update_major": "有重大更新",
    "update_minor": "有功能更新",
    "update_patch": "有修正更新",
    "invalid": "無法判讀版本",
}

_MAX_VERSION_LENGTH = 128
_MAX_PAYLOAD_BYTES = 64 * 1024
_MAX_RELEASE_NAME_LENGTH = 200
_MAX_PUBLISHED_AT_LENGTH = 40

# A leading ``v`` is conventional for release tags but optional here because
# CURRENT_VERSION deliberately contains only the semantic-version triplet.
_VERSION_RE = re.compile(
    r"^(?:v)?"
    r"(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"$"
)
_PUBLISHED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})$")


@dataclass(frozen=True, slots=True)
class VersionGap:
    """A safe, normalized comparison result.

    ``distance`` is ``latest - current`` component by component.  Semantic
    versions do not define a total count of intervening releases, so a signed
    triplet is more honest than inventing a scalar distance.  UI code should
    use the component named by ``kind`` (major, minor, or patch).
    """

    current: str
    latest: str
    kind: VersionKind
    distance: VersionTuple | None

    @property
    def label(self) -> str:
        """Return the short Traditional-Chinese label intended for the UI."""
        return VERSION_KIND_LABELS[self.kind]

    @property
    def update_available(self) -> bool:
        return self.kind.startswith("update_")


@dataclass(frozen=True, slots=True)
class LatestRelease:
    """Validated subset of GitHub's latest-release response.

    Remote URL fields are deliberately not represented.  ``release_url`` is
    fixed at build time so an API response cannot redirect the UI to an
    arbitrary website.
    """

    tag_name: str
    name: str
    published_at: str | None
    version: str
    sha256: str | None = None
    git_commit: str | None = None
    release_url: str = field(default=LATEST_RELEASE_URL, kw_only=True)

    @property
    def version_tuple(self) -> VersionTuple:
        # Construction is private to the validated parser, so this is total.
        parsed = parse_version(self.version)
        assert parsed is not None
        return parsed

    @property
    def url(self) -> str:
        """Concise compatibility alias for UI code."""
        return self.release_url


def parse_version(value: object) -> VersionTuple | None:
    """Parse a safe SemVer triplet, ignoring valid pre-release/build suffixes.

    Both ``4.1.0`` and ``v4.1.0`` are accepted.  Surrounding Unicode
    whitespace is ignored; internal whitespace, Unicode digits, leading zeroes
    and malformed suffixes are rejected.  This function never raises for
    malformed input.
    """

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text or len(text) > _MAX_VERSION_LENGTH:
        return None

    match = _VERSION_RE.fullmatch(text)
    if match is None:
        return None

    prerelease = match.group("prerelease")
    if prerelease is not None:
        # SemVer numeric pre-release identifiers must not have leading zeroes.
        if any(
            identifier.isascii()
            and identifier.isdigit()
            and len(identifier) > 1
            and identifier.startswith("0")
            for identifier in prerelease.split(".")
        ):
            return None

    try:
        return (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("patch")),
        )
    except (TypeError, ValueError):
        return None


def format_version(version: VersionTuple) -> str:
    """Return the canonical display form without a tag prefix or suffix."""
    return ".".join(str(component) for component in version)


def compare_versions(current: object, latest: object) -> VersionGap:
    """Classify two versions without raising on malformed values."""

    current_version = parse_version(current)
    latest_version = parse_version(latest)
    if current_version is None or latest_version is None:
        return VersionGap(current="", latest="", kind="invalid", distance=None)

    current_text = format_version(current_version)
    latest_text = format_version(latest_version)
    distance: VersionTuple = tuple(
        latest_part - current_part
        for current_part, latest_part in zip(current_version, latest_version)
    )  # type: ignore[assignment]

    if latest_version == current_version:
        kind: VersionKind = "current"
    elif latest_version < current_version:
        kind = "ahead"
    elif latest_version[0] > current_version[0]:
        kind = "update_major"
    elif latest_version[1] > current_version[1]:
        kind = "update_minor"
    else:
        kind = "update_patch"

    return VersionGap(
        current=current_text,
        latest=latest_text,
        kind=kind,
        distance=distance,
    )


def assess_version_gap(
    latest: object,
    current: object = CURRENT_VERSION,
) -> VersionGap:
    """Convenience wrapper for checking a fetched release against this app."""
    return compare_versions(current=current, latest=latest)


def version_kind_label(kind: str) -> str:
    """Return a UI label while safely handling unknown future values."""
    return VERSION_KIND_LABELS.get(kind, VERSION_KIND_LABELS["invalid"])


def _has_unsafe_text_characters(value: str) -> bool:
    # Cc covers line breaks/control characters; Cf covers invisible formatting
    # and bidi-override characters that can make remote UI text misleading.
    return any(unicodedata.category(character) in {"Cc", "Cf"} for character in value)


def _validated_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if (
        not text
        or len(text) > _MAX_RELEASE_NAME_LENGTH
        or _has_unsafe_text_characters(text)
    ):
        return None
    return text


def _validated_published_at(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if (
        not text
        or len(text) > _MAX_PUBLISHED_AT_LENGTH
        or _PUBLISHED_AT_RE.fullmatch(text) is None
    ):
        return None

    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_payload(payload: bytes | str | dict[object, object]) -> dict[object, object] | None:
    if isinstance(payload, bytes):
        if len(payload) > _MAX_PAYLOAD_BYTES:
            return None
        try:
            # Tolerate manifests produced by legacy Windows PowerShell, whose
            # ``-Encoding UTF8`` includes a BOM.  New builds write BOM-less
            # UTF-8, but accepting the older form keeps published releases
            # readable.
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
    elif isinstance(payload, str):
        try:
            if len(payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
                return None
        except UnicodeEncodeError:
            return None
        text = payload.removeprefix("\ufeff")
    elif isinstance(payload, dict):
        return payload
    else:
        return None

    try:
        decoded = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def parse_latest_release_payload(
    payload: bytes | str | dict[object, object],
) -> LatestRelease | None:
    """Validate and reduce a GitHub latest-release payload.

    The parser is deliberately fail-closed: malformed JSON, missing or unsafe
    fields, invalid timestamps and invalid tags all return ``None``.  Fields
    such as ``html_url`` are ignored and can never influence ``release_url``.
    """

    decoded = _decode_payload(payload)
    if decoded is None:
        return None

    raw_tag = decoded.get("tag_name")
    if not isinstance(raw_tag, str):
        return None
    tag_name = raw_tag.strip()
    # GitHub release tags for this project must use the explicit lower-case v
    # prefix.  The SemVer parser itself remains useful for CURRENT_VERSION too.
    if not tag_name.startswith("v"):
        return None
    parsed_version = parse_version(tag_name)
    if parsed_version is None:
        return None

    name = _validated_name(decoded.get("name"))
    published_at = _validated_published_at(decoded.get("published_at"))
    if name is None or published_at is None:
        return None

    return LatestRelease(
        tag_name=tag_name,
        name=name,
        published_at=published_at,
        version=format_version(parsed_version),
    )


def parse_release_manifest_payload(
    payload: bytes | str | dict[object, object],
) -> LatestRelease | None:
    """Validate the release's required build manifest.

    A usable manifest must describe the expected executable, originate from a
    clean Git worktree and include both a full commit id and executable digest.
    As with the REST parser, all remote URL fields are ignored; the returned URL
    is constructed exclusively from this repository's constant prefix and the
    already-validated semantic version.
    """

    decoded = _decode_payload(payload)
    if decoded is None:
        return None

    raw_version = decoded.get("appVersion")
    if not isinstance(raw_version, str):
        return None
    app_version = raw_version.strip()
    if not app_version or app_version.startswith("v"):
        return None
    parsed_version = parse_version(app_version)
    if parsed_version is None:
        return None

    # ``is`` matters: JSON number 0 must not be accepted as boolean false.
    if decoded.get("gitDirty") is not False:
        return None
    if decoded.get("exeName") != EXPECTED_EXE_NAME:
        return None

    raw_sha256 = decoded.get("sha256")
    if not isinstance(raw_sha256, str) or _SHA256_RE.fullmatch(raw_sha256) is None:
        return None
    sha256 = raw_sha256.lower()

    raw_commit = decoded.get("gitCommit")
    if not isinstance(raw_commit, str) or _GIT_COMMIT_RE.fullmatch(raw_commit) is None:
        return None
    git_commit = raw_commit.lower()

    tag_name = f"v{app_version}"
    return LatestRelease(
        tag_name=tag_name,
        name=f"管線流程工具 {tag_name}",
        published_at=None,
        version=format_version(parsed_version),
        sha256=sha256,
        git_commit=git_commit,
        release_url=f"{RELEASE_TAG_URL_PREFIX}{tag_name}",
    )


__all__ = [
    "CURRENT_VERSION",
    "EXPECTED_EXE_NAME",
    "LATEST_RELEASE_URL",
    "RELEASE_TAG_URL_PREFIX",
    "LatestRelease",
    "VERSION_KIND_LABELS",
    "VersionGap",
    "VersionKind",
    "VersionTuple",
    "assess_version_gap",
    "compare_versions",
    "format_version",
    "parse_latest_release_payload",
    "parse_release_manifest_payload",
    "parse_version",
    "version_kind_label",
]
