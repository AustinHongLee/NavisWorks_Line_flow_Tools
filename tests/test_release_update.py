# -*- coding: utf-8 -*-
from __future__ import annotations

import dataclasses
import json
import unittest

from core.release_update import (
    CURRENT_VERSION,
    EXPECTED_EXE_NAME,
    LATEST_RELEASE_URL,
    RELEASE_TAG_URL_PREFIX,
    VERSION_KIND_LABELS,
    LatestRelease,
    VersionGap,
    assess_version_gap,
    compare_versions,
    format_version,
    parse_latest_release_payload,
    parse_release_manifest_payload,
    parse_version,
    version_kind_label,
)


VALID_PAYLOAD = {
    "tag_name": "v4.2.3",
    "name": "管線流程工具 v4.2.3",
    "published_at": "2026-08-11T04:05:06Z",
}

VALID_MANIFEST = {
    "appVersion": "4.2.3",
    "exeName": EXPECTED_EXE_NAME,
    "gitCommit": "bcd0d56b926c15ff4661cc1bd2f7798a789fe942",
    "gitDirty": False,
    "sha256": "6c406ad1ceff97e3e5d3bfd25569a47ba16f04cef393cd41ee5deadd03fa05b1",
}


class VersionParsingTests(unittest.TestCase):
    def test_current_version_is_the_expected_triplet(self):
        self.assertEqual(CURRENT_VERSION, "4.1.1")
        self.assertEqual(parse_version(CURRENT_VERSION), (4, 1, 1))

    def test_accepts_release_prefix_and_surrounding_unicode_whitespace(self):
        self.assertEqual(parse_version("\u3000 v12.34.56 \n"), (12, 34, 56))

    def test_ignores_valid_prerelease_and_build_suffixes(self):
        self.assertEqual(parse_version("v4.2.0-rc.1+build.20260811"), (4, 2, 0))
        self.assertEqual(parse_version("4.2.0+001"), (4, 2, 0))

    def test_accepts_zeroes_and_large_components(self):
        huge = "123456789012345678901234567890"
        self.assertEqual(parse_version(f"v{huge}.0.9"), (int(huge), 0, 9))
        self.assertEqual(format_version((0, 0, 0)), "0.0.0")

    def test_rejects_incomplete_or_extra_core_components(self):
        invalid = ("", "v1", "v1.2", "v1.2.3.4", "v.1.2.3", "version1.2.3")
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_rejects_leading_zeroes_and_unicode_digits(self):
        invalid = ("v01.2.3", "v1.02.3", "v1.2.03", "v١.2.3")
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_rejects_malformed_suffixes(self):
        invalid = (
            "v1.2.3-",
            "v1.2.3+",
            "v1.2.3-alpha..1",
            "v1.2.3-01",
            "v1.2.3-alpha_1",
            "v1.2.3+build/1",
            "v1.2.3+build+again",
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_rejects_internal_whitespace_uppercase_prefix_and_non_strings(self):
        invalid = ("v1. 2.3", "V1.2.3", None, 123, b"v1.2.3")
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(parse_version(value))

    def test_rejects_unreasonably_long_version_text(self):
        self.assertIsNone(parse_version("v" + "1" * 129 + ".0.0"))


class VersionComparisonTests(unittest.TestCase):
    def test_current_ignores_release_suffix(self):
        result = compare_versions("4.1.0", "v4.1.0+build.5")
        self.assertEqual(result, VersionGap("4.1.0", "4.1.0", "current", (0, 0, 0)))
        self.assertEqual(result.label, "已是最新版")
        self.assertFalse(result.update_available)

    def test_detects_major_update_with_signed_component_distance(self):
        result = compare_versions("4.9.8", "v5.0.1")
        self.assertEqual(result.kind, "update_major")
        self.assertEqual(result.distance, (1, -9, -7))
        self.assertTrue(result.update_available)

    def test_detects_minor_update(self):
        result = compare_versions("4.1.9", "v4.3.0")
        self.assertEqual(result.kind, "update_minor")
        self.assertEqual(result.distance, (0, 2, -9))

    def test_detects_patch_update(self):
        result = compare_versions("4.1.0", "v4.1.7")
        self.assertEqual(result.kind, "update_patch")
        self.assertEqual(result.distance, (0, 0, 7))

    def test_detects_local_version_ahead(self):
        result = compare_versions("5.0.0", "v4.9.9")
        self.assertEqual(result.kind, "ahead")
        self.assertEqual(result.distance, (-1, 9, 9))
        self.assertEqual(result.label, "本機版本較新")

    def test_invalid_current_or_latest_is_fail_closed_and_does_not_raise(self):
        for current, latest in (
            ("bad", "v4.2.0"),
            ("4.1.0", "latest"),
            (None, {}),
            (object(), object()),
        ):
            with self.subTest(current=current, latest=latest):
                result = compare_versions(current, latest)
                self.assertEqual(result.kind, "invalid")
                self.assertEqual(result.current, "")
                self.assertEqual(result.latest, "")
                self.assertIsNone(result.distance)
                self.assertFalse(result.update_available)

    def test_default_current_version_convenience_api(self):
        result = assess_version_gap("v4.2.0")
        self.assertEqual((result.current, result.latest, result.kind), (
            "4.1.1",
            "4.2.0",
            "update_minor",
        ))

    def test_every_kind_has_a_short_traditional_chinese_label(self):
        expected_kinds = {
            "current",
            "ahead",
            "update_major",
            "update_minor",
            "update_patch",
            "invalid",
        }
        self.assertEqual(set(VERSION_KIND_LABELS), expected_kinds)
        for kind, label in VERSION_KIND_LABELS.items():
            with self.subTest(kind=kind):
                self.assertTrue(label)
                self.assertLessEqual(len(label), 8)
        self.assertEqual(version_kind_label("future_kind"), "無法判讀版本")

    def test_result_dataclass_is_frozen(self):
        result = assess_version_gap("v4.2.0")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.kind = "current"  # type: ignore[misc]


class LatestReleasePayloadTests(unittest.TestCase):
    def test_parses_dict_and_normalizes_version(self):
        result = parse_latest_release_payload(VALID_PAYLOAD)
        self.assertEqual(
            result,
            LatestRelease(
                tag_name="v4.2.3",
                name="管線流程工具 v4.2.3",
                published_at="2026-08-11T04:05:06Z",
                version="4.2.3",
            ),
        )
        assert result is not None
        self.assertEqual(result.version_tuple, (4, 2, 3))

    def test_parses_utf8_json_as_str_and_bytes(self):
        text = json.dumps(VALID_PAYLOAD, ensure_ascii=False)
        for payload in (text, text.encode("utf-8")):
            with self.subTest(payload_type=type(payload).__name__):
                result = parse_latest_release_payload(payload)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.name, VALID_PAYLOAD["name"])

    def test_validates_and_ignores_release_suffix(self):
        payload = dict(VALID_PAYLOAD, tag_name="v4.2.3-rc.1+build.9")
        result = parse_latest_release_payload(payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.version, "4.2.3")
        self.assertEqual(result.tag_name, "v4.2.3-rc.1+build.9")

    def test_remote_urls_are_never_trusted(self):
        payload = dict(
            VALID_PAYLOAD,
            html_url="https://evil.example/download",
            url="file:///C:/Windows/System32/calc.exe",
        )
        result = parse_latest_release_payload(payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.release_url, LATEST_RELEASE_URL)
        self.assertEqual(result.url, LATEST_RELEASE_URL)
        self.assertNotIn("evil.example", result.release_url)

    def test_rejects_missing_required_fields(self):
        for field in ("tag_name", "name", "published_at"):
            payload = dict(VALID_PAYLOAD)
            payload.pop(field)
            with self.subTest(field=field):
                self.assertIsNone(parse_latest_release_payload(payload))

    def test_rejects_wrong_field_types_and_empty_text(self):
        invalid_changes = (
            {"tag_name": None},
            {"tag_name": 420},
            {"name": None},
            {"name": "   "},
            {"published_at": None},
            {"published_at": 0},
        )
        for change in invalid_changes:
            payload = dict(VALID_PAYLOAD, **change)
            with self.subTest(change=change):
                self.assertIsNone(parse_latest_release_payload(payload))

    def test_release_payload_requires_lowercase_v_tag_prefix(self):
        for tag in ("4.2.3", "V4.2.3", "release-v4.2.3", "v04.2.3"):
            with self.subTest(tag=tag):
                self.assertIsNone(
                    parse_latest_release_payload(dict(VALID_PAYLOAD, tag_name=tag))
                )

    def test_trims_safe_fields(self):
        payload = dict(
            VALID_PAYLOAD,
            tag_name="  v4.2.3  ",
            name="  管線流程工具 v4.2.3  ",
            published_at="  2026-08-11T04:05:06Z  ",
        )
        result = parse_latest_release_payload(payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tag_name, "v4.2.3")
        self.assertEqual(result.name, "管線流程工具 v4.2.3")
        self.assertEqual(result.published_at, "2026-08-11T04:05:06Z")

    def test_rejects_invalid_or_naive_timestamp(self):
        invalid = (
            "2026-08-11T04:05:06",
            "2026-13-11T04:05:06Z",
            "2026-02-29T04:05:06Z",
            "2026-08-11 04:05:06Z",
            "yesterday",
        )
        for published_at in invalid:
            with self.subTest(published_at=published_at):
                payload = dict(VALID_PAYLOAD, published_at=published_at)
                self.assertIsNone(parse_latest_release_payload(payload))

    def test_accepts_fractional_seconds_and_explicit_offset(self):
        for published_at in (
            "2026-08-11T04:05:06.123456Z",
            "2026-08-11T12:05:06+08:00",
        ):
            with self.subTest(published_at=published_at):
                payload = dict(VALID_PAYLOAD, published_at=published_at)
                self.assertIsNotNone(parse_latest_release_payload(payload))

    def test_rejects_control_or_bidi_characters_in_remote_name(self):
        for name in ("release\nspoof", "release\x00spoof", "safe\u202eevil"):
            with self.subTest(name=repr(name)):
                self.assertIsNone(
                    parse_latest_release_payload(dict(VALID_PAYLOAD, name=name))
                )

    def test_rejects_excessively_long_fields_and_payloads(self):
        self.assertIsNone(
            parse_latest_release_payload(dict(VALID_PAYLOAD, name="x" * 201))
        )
        oversized = "{" + (" " * (64 * 1024)) + "}"
        self.assertIsNone(parse_latest_release_payload(oversized))
        self.assertIsNone(parse_latest_release_payload(oversized.encode("utf-8")))

    def test_rejects_malformed_json_invalid_utf8_and_non_objects(self):
        invalid = (
            "{",
            b"\xff\xfe",
            "[]",
            "null",
            [VALID_PAYLOAD],
            bytearray(b"{}"),
            123,
            None,
        )
        for payload in invalid:
            with self.subTest(payload=repr(payload)[:40]):
                self.assertIsNone(parse_latest_release_payload(payload))  # type: ignore[arg-type]

    def test_rejects_duplicate_json_keys(self):
        duplicate = (
            '{"tag_name":"v4.2.3","tag_name":"v99.0.0",'
            '"name":"release","published_at":"2026-08-11T04:05:06Z"}'
        )
        self.assertIsNone(parse_latest_release_payload(duplicate))

    def test_release_dataclass_is_frozen(self):
        result = parse_latest_release_payload(VALID_PAYLOAD)
        assert result is not None
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.release_url = "https://evil.example"  # type: ignore[misc]


class ReleaseManifestPayloadTests(unittest.TestCase):
    def test_parses_verified_manifest_metadata(self):
        result = parse_release_manifest_payload(VALID_MANIFEST)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tag_name, "v4.2.3")
        self.assertEqual(result.name, "管線流程工具 v4.2.3")
        self.assertIsNone(result.published_at)
        self.assertEqual(result.version, "4.2.3")
        self.assertEqual(result.sha256, VALID_MANIFEST["sha256"])
        self.assertEqual(result.git_commit, VALID_MANIFEST["gitCommit"])
        self.assertEqual(
            result.release_url,
            f"{RELEASE_TAG_URL_PREFIX}v4.2.3",
        )

    def test_parses_manifest_from_json_string_and_bytes(self):
        text = json.dumps(VALID_MANIFEST)
        for payload in (
            text,
            text.encode("utf-8"),
            "\ufeff" + text,
            b"\xef\xbb\xbf" + text.encode("utf-8"),
        ):
            with self.subTest(payload_type=type(payload).__name__):
                self.assertIsNotNone(parse_release_manifest_payload(payload))

    def test_manifest_accepts_valid_suffix_but_compares_core_triplet(self):
        manifest = dict(VALID_MANIFEST, appVersion="4.2.3-rc.1+build.9")
        result = parse_release_manifest_payload(manifest)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.version, "4.2.3")
        self.assertEqual(result.tag_name, "v4.2.3-rc.1+build.9")
        self.assertTrue(result.release_url.endswith("/v4.2.3-rc.1+build.9"))

    def test_manifest_requires_unprefixed_strict_semver(self):
        for app_version in (
            "v4.2.3",
            "04.2.3",
            "4.2",
            "4.2.3-01",
            "latest",
            None,
        ):
            with self.subTest(app_version=app_version):
                manifest = dict(VALID_MANIFEST, appVersion=app_version)
                self.assertIsNone(parse_release_manifest_payload(manifest))

    def test_manifest_requires_literal_false_git_dirty(self):
        for git_dirty in (True, 0, 1, "false", None):
            with self.subTest(git_dirty=git_dirty):
                manifest = dict(VALID_MANIFEST, gitDirty=git_dirty)
                self.assertIsNone(parse_release_manifest_payload(manifest))

    def test_manifest_requires_exact_executable_name(self):
        for exe_name in (
            "navisworks_line_flow_tools.exe",
            "NavisWorks_Line_flow_Tools.exe ",
            "other.exe",
            None,
        ):
            with self.subTest(exe_name=exe_name):
                manifest = dict(VALID_MANIFEST, exeName=exe_name)
                self.assertIsNone(parse_release_manifest_payload(manifest))

    def test_manifest_requires_exactly_64_hex_digest(self):
        invalid = (
            "a" * 63,
            "a" * 65,
            "g" * 64,
            "00" * 32 + " ",
            None,
        )
        for sha256 in invalid:
            with self.subTest(sha256=sha256):
                manifest = dict(VALID_MANIFEST, sha256=sha256)
                self.assertIsNone(parse_release_manifest_payload(manifest))

        upper = dict(VALID_MANIFEST, sha256="A" * 64)
        result = parse_release_manifest_payload(upper)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.sha256, "a" * 64)

    def test_manifest_requires_full_git_commit_hash(self):
        invalid = ("bcd0d56", "z" * 40, "a" * 39, "a" * 41, None)
        for commit in invalid:
            with self.subTest(commit=commit):
                manifest = dict(VALID_MANIFEST, gitCommit=commit)
                self.assertIsNone(parse_release_manifest_payload(manifest))

        sha256_commit = dict(VALID_MANIFEST, gitCommit="A" * 64)
        result = parse_release_manifest_payload(sha256_commit)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.git_commit, "a" * 64)

    def test_manifest_requires_every_integrity_field(self):
        for field in ("appVersion", "exeName", "gitCommit", "gitDirty", "sha256"):
            manifest = dict(VALID_MANIFEST)
            manifest.pop(field)
            with self.subTest(field=field):
                self.assertIsNone(parse_release_manifest_payload(manifest))

    def test_manifest_never_trusts_remote_urls_or_labels(self):
        manifest = dict(
            VALID_MANIFEST,
            html_url="https://evil.example/phishing",
            release_url="file:///C:/Windows/System32/calc.exe",
            name="Fake security update",
            published_at="not-a-date",
        )
        result = parse_release_manifest_payload(manifest)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.name, "管線流程工具 v4.2.3")
        self.assertEqual(result.release_url, f"{RELEASE_TAG_URL_PREFIX}v4.2.3")

    def test_manifest_reuses_safe_json_boundaries(self):
        self.assertIsNone(parse_release_manifest_payload("{"))
        self.assertIsNone(parse_release_manifest_payload(b"\xff"))
        self.assertIsNone(parse_release_manifest_payload("[]"))
        self.assertIsNone(parse_release_manifest_payload(None))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
