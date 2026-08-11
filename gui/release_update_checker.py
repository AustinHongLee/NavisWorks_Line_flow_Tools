"""Non-blocking, cached check of the latest published EXE manifest."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from PyQt6.QtCore import QObject, QSettings, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from core.release_update import (
    CURRENT_VERSION,
    EXPECTED_EXE_NAME,
    LatestRelease,
    parse_release_manifest_payload,
)


LATEST_MANIFEST_URL = (
    "https://github.com/AustinHongLee/NavisWorks_Line_flow_Tools/"
    "releases/latest/download/NavisWorks_Line_flow_Tools.manifest.json"
)
CACHE_PREFIX = "releaseUpdate/"
CACHE_TTL = timedelta(hours=24)
FAILURE_BACKOFF = timedelta(hours=1)
MAX_RESPONSE_BYTES = 128 * 1024
ALLOWED_FINAL_HOSTS = frozenset(
    {"github.com", "release-assets.githubusercontent.com"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ReleaseUpdateChecker(QObject):
    """Read the required manifest asset without blocking or stealing focus."""

    release_ready = pyqtSignal(object)
    check_failed = pyqtSignal(str)
    checking_changed = pyqtSignal(bool)

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        manager: QNetworkAccessManager | None = None,
        manifest_url: str = LATEST_MANIFEST_URL,
        transfer_timeout_ms: int = 4_000,
        deadline_ms: int = 8_000,
        cache_ttl: timedelta = CACHE_TTL,
        failure_backoff: timedelta = FAILURE_BACKOFF,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._manager = manager or QNetworkAccessManager(self)
        self._manifest_url = manifest_url
        self._transfer_timeout_ms = max(500, int(transfer_timeout_ms))
        self._deadline_ms = max(
            self._transfer_timeout_ms,
            int(deadline_ms),
        )
        self._cache_ttl = cache_ttl
        self._failure_backoff = failure_backoff
        self._reply: QNetworkReply | None = None
        self._closing = False
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._on_deadline)

    @property
    def is_checking(self) -> bool:
        return self._reply is not None

    def start(self, *, force: bool = False) -> None:
        if self._closing or self._reply is not None:
            return

        cached, checked_at, failed_at = self._load_cache()
        now = _utc_now()
        if (
            not force
            and cached is not None
            and checked_at is not None
            and now - checked_at <= self._cache_ttl
        ):
            self.release_ready.emit(cached)
            return
        if (
            not force
            and failed_at is not None
            and now - failed_at <= self._failure_backoff
        ):
            if cached is not None:
                self.release_ready.emit(cached)
            else:
                self.check_failed.emit("offline-backoff")
            return

        # An older cache is still useful when the refresh fails.  Emit it
        # first, then refresh quietly in the background.
        if cached is not None:
            self.release_ready.emit(cached)

        request = QNetworkRequest(QUrl(self._manifest_url))
        request.setTransferTimeout(self._transfer_timeout_ms)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setMaximumRedirectsAllowed(3)
        request.setRawHeader(
            b"User-Agent",
            f"PipelineOps/{CURRENT_VERSION}".encode("ascii", errors="strict"),
        )
        request.setRawHeader(
            b"Accept", b"application/json, application/octet-stream"
        )

        # Cache/backoff entries belong to the executable version that created
        # them.  A newly installed build must refresh instead of briefly
        # presenting an older build's cached Release as current truth.
        self._set_setting("localVersion", CURRENT_VERSION)
        self._set_setting("lastAttemptAt", now.isoformat())
        reply = self._manager.get(request)
        self._reply = reply
        self.checking_changed.emit(True)
        self._deadline.start(self._deadline_ms)
        reply.finished.connect(lambda current=reply: self._on_finished(current))

    def cancel(self) -> None:
        self._closing = True
        self._deadline.stop()
        reply = self._reply
        self._reply = None
        if reply is not None:
            try:
                reply.abort()
            except RuntimeError:
                pass
            reply.deleteLater()
            self.checking_changed.emit(False)

    def _on_deadline(self) -> None:
        reply = self._reply
        if reply is None:
            return
        try:
            reply.abort()
        except RuntimeError:
            pass

    def _on_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            reply.deleteLater()
            return

        self._reply = None
        self._deadline.stop()
        self.checking_changed.emit(False)
        try:
            status_value = reply.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute
            )
            status = int(status_value or 0)
            final_url = reply.url()
            if (
                reply.error() != QNetworkReply.NetworkError.NoError
                or status != 200
            ):
                self._record_failure("network-unavailable")
                return
            if (
                final_url.scheme().lower() != "https"
                or final_url.host().lower() not in ALLOWED_FINAL_HOSTS
            ):
                self._record_failure("unsafe-redirect")
                return

            payload = bytes(reply.readAll())
            if not payload or len(payload) > MAX_RESPONSE_BYTES:
                self._record_failure("invalid-response-size")
                return
            release = parse_release_manifest_payload(payload)
            if release is None:
                self._record_failure("invalid-release-manifest")
                return

            self._save_cache(release)
            self.release_ready.emit(release)
        finally:
            reply.deleteLater()

    def _record_failure(self, reason: str) -> None:
        self._set_setting("lastFailureAt", _utc_now().isoformat())
        self.check_failed.emit(reason)

    def _load_cache(
        self,
    ) -> tuple[LatestRelease | None, datetime | None, datetime | None]:
        if self._settings is None:
            return None, None, None
        cached_for_version = str(
            self._settings.value(CACHE_PREFIX + "localVersion", "") or ""
        ).strip()
        if cached_for_version != CURRENT_VERSION:
            return None, None, None
        version = str(
            self._settings.value(CACHE_PREFIX + "appVersion", "") or ""
        ).strip()
        payload: dict[str, Any] = {
            "appVersion": version,
            "exeName": str(
                self._settings.value(CACHE_PREFIX + "exeName", "") or ""
            ),
            "sha256": str(
                self._settings.value(CACHE_PREFIX + "sha256", "") or ""
            ),
            "gitCommit": str(
                self._settings.value(CACHE_PREFIX + "gitCommit", "") or ""
            ),
            "gitDirty": False,
        }
        release: LatestRelease | None = None
        if version:
            release = parse_release_manifest_payload(payload)
        checked_at = _parse_utc(
            self._settings.value(CACHE_PREFIX + "checkedAt", "")
        )
        failed_at = _parse_utc(
            self._settings.value(CACHE_PREFIX + "lastFailureAt", "")
        )
        return release, checked_at, failed_at

    def _save_cache(self, release: LatestRelease) -> None:
        if self._settings is None:
            return
        self._settings.setValue(CACHE_PREFIX + "localVersion", CURRENT_VERSION)
        self._settings.setValue(CACHE_PREFIX + "appVersion", release.version)
        self._settings.setValue(CACHE_PREFIX + "exeName", EXPECTED_EXE_NAME)
        self._settings.setValue(CACHE_PREFIX + "sha256", release.sha256 or "")
        self._settings.setValue(
            CACHE_PREFIX + "gitCommit", release.git_commit or ""
        )
        self._settings.setValue(
            CACHE_PREFIX + "checkedAt", _utc_now().isoformat()
        )
        self._settings.remove(CACHE_PREFIX + "lastFailureAt")
        self._settings.sync()

    def _set_setting(self, key: str, value: object) -> None:
        if self._settings is None:
            return
        self._settings.setValue(CACHE_PREFIX + key, value)
        self._settings.sync()


__all__ = [
    "CACHE_TTL",
    "FAILURE_BACKOFF",
    "LATEST_MANIFEST_URL",
    "ReleaseUpdateChecker",
]
