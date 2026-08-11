from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtNetwork import QNetworkRequest
from PyQt6.QtWidgets import QApplication

from core.release_update import CURRENT_VERSION, parse_release_manifest_payload
from gui.release_update_checker import CACHE_PREFIX, ReleaseUpdateChecker


VALID_MANIFEST = {
    "appVersion": "4.2.0",
    "exeName": "NavisWorks_Line_flow_Tools.exe",
    "gitCommit": "bcd0d56b926c15ff4661cc1bd2f7798a789fe942",
    "gitDirty": False,
    "sha256": "6c406ad1ceff97e3e5d3bfd25569a47ba16f04cef393cd41ee5deadd03fa05b1",
}


def _settings(tmp_path) -> QSettings:
    return QSettings(
        str(tmp_path / "release-check.ini"),
        QSettings.Format.IniFormat,
    )


def test_fresh_manifest_cache_returns_without_network(tmp_path):
    QApplication.instance() or QApplication([])
    settings = _settings(tmp_path)
    release = parse_release_manifest_payload(VALID_MANIFEST)
    assert release is not None
    checker = ReleaseUpdateChecker(settings=settings)
    checker._save_cache(release)
    received = []
    checking = []
    checker.release_ready.connect(received.append)
    checker.checking_changed.connect(checking.append)

    checker.start()

    assert received == [release]
    assert checking == []
    assert not checker.is_checking


def test_recent_offline_failure_uses_backoff_without_network(tmp_path):
    QApplication.instance() or QApplication([])
    settings = _settings(tmp_path)
    settings.setValue(CACHE_PREFIX + "localVersion", CURRENT_VERSION)
    settings.setValue(
        CACHE_PREFIX + "lastFailureAt",
        datetime.now(timezone.utc).isoformat(),
    )
    settings.sync()
    checker = ReleaseUpdateChecker(settings=settings)
    failures = []
    checker.check_failed.connect(failures.append)

    checker.start()

    assert failures == ["offline-backoff"]
    assert not checker.is_checking


def test_cancel_is_idempotent_before_any_request(tmp_path):
    QApplication.instance() or QApplication([])
    checker = ReleaseUpdateChecker(settings=_settings(tmp_path))

    checker.cancel()
    checker.cancel()
    checker.start(force=True)

    assert not checker.is_checking


def test_cache_and_failure_backoff_are_invalidated_after_app_upgrade(tmp_path):
    QApplication.instance() or QApplication([])
    settings = _settings(tmp_path)
    release = parse_release_manifest_payload(VALID_MANIFEST)
    assert release is not None
    checker = ReleaseUpdateChecker(settings=settings)
    checker._save_cache(release)
    settings.setValue(CACHE_PREFIX + "localVersion", "4.0.0")
    settings.setValue(
        CACHE_PREFIX + "lastFailureAt",
        datetime.now(timezone.utc).isoformat(),
    )
    settings.sync()

    cached, checked_at, failed_at = checker._load_cache()

    assert CURRENT_VERSION != "4.0.0"
    assert (cached, checked_at, failed_at) == (None, None, None)


def test_network_request_is_https_limited_and_never_started_in_test(tmp_path):
    QApplication.instance() or QApplication([])

    class InspectingManager:
        @staticmethod
        def get(request):
            assert request.url().scheme() == "https"
            assert request.maximumRedirectsAllowed() == 3
            assert request.attribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute
            ) == QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
            raise RuntimeError("request-inspected")

    checker = ReleaseUpdateChecker(
        settings=_settings(tmp_path),
        manager=InspectingManager(),
    )

    with pytest.raises(RuntimeError, match="request-inspected"):
        checker.start(force=True)
