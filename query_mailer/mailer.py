from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings
from .core import (
    notification_snapshot,
    render_feishu_raw_message,
    render_feishu_summary_message,
    utc_now_text,
)
from .storage import load_record, update_record


def _channel_keys(channel: str) -> tuple[str, str, str, str]:
    return (
        f"{channel}_status",
        f"{channel}_error",
        f"{channel}_attempts",
        f"last_{channel}_attempt_at_utc",
    )


def _legacy_backfill(record_path: Path, record: dict) -> dict:
    if "summary_status" in record or "raw_status" in record:
        return record

    legacy_status = str(record.get("mail_status", "not_attempted"))
    legacy_error = str(record.get("mail_error", ""))
    legacy_attempts = int(record.get("mail_attempts", 0))
    legacy_last = str(record.get("last_mail_attempt_at_utc", ""))
    request_status = str(record.get("request_status", ""))

    updates: dict[str, object]
    if request_status == "accepted":
        updates = {
            "summary_status": legacy_status,
            "summary_error": legacy_error,
            "summary_attempts": legacy_attempts,
            "last_summary_attempt_at_utc": legacy_last,
            "raw_status": "skipped",
            "raw_error": "Legacy record has no raw notification channel state.",
            "raw_attempts": 0,
            "last_raw_attempt_at_utc": "",
        }
    else:
        updates = {
            "summary_status": "skipped",
            "summary_error": "Summary notifications are only sent for accepted requests.",
            "summary_attempts": 0,
            "last_summary_attempt_at_utc": "",
            "raw_status": legacy_status,
            "raw_error": legacy_error,
            "raw_attempts": legacy_attempts,
            "last_raw_attempt_at_utc": legacy_last,
        }

    updated = {**record, **updates}
    updated.update(notification_snapshot(updated))
    update_record(record_path, **updates, **notification_snapshot(updated))
    return updated


def _persist_channel_update(record_path: Path, record: dict, channel: str, **changes: object) -> dict:
    updated = {**record, **changes}
    snapshot = notification_snapshot(updated)
    return update_record(record_path, **changes, **snapshot)


def _channel_payload(record: dict, settings: Settings, channel: str) -> tuple[str, str]:
    if channel == "summary":
        if record.get("request_status") != "accepted":
            return "", ""
        return settings.feishu_webhook, render_feishu_summary_message(record, settings)
    if channel == "raw":
        return settings.feishu_rejected_webhook, render_feishu_raw_message(record, settings)
    raise ValueError(f"Unsupported channel: {channel}")


def _response_error(response_body: str) -> str:
    if not response_body.strip():
        return ""
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError:
        return ""

    for key in ("StatusCode", "code", "errcode"):
        value = payload.get(key)
        if value not in (None, 0, "0"):
            return f"{key}={value}"
    return ""


def _deliver_channel(record_path: Path, settings: Settings, channel: str) -> dict:
    record = _legacy_backfill(record_path, load_record(record_path))
    status_key, error_key, attempts_key, last_attempt_key = _channel_keys(channel)
    channel_status = str(record.get(status_key, ""))
    if channel_status not in {"pending", "failed"}:
        return record

    webhook_url, message = _channel_payload(record, settings, channel)
    attempts = int(record.get(attempts_key, 0)) + 1
    attempted_at = utc_now_text()

    if not webhook_url:
        return _persist_channel_update(
            record_path,
            record,
            channel,
            **{
                status_key: "failed",
                error_key: f"No webhook configured for {channel} notifications.",
                attempts_key: attempts,
                last_attempt_key: attempted_at,
            },
        )

    payload = json.dumps(
        {
            "msg_type": "text",
            "content": {"text": message},
        }
    ).encode("utf-8")

    request = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.webhook_timeout_seconds) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return _persist_channel_update(
            record_path,
            record,
            channel,
            **{
                status_key: "failed",
                error_key: f"HTTPError {exc.code}: {body}",
                attempts_key: attempts,
                last_attempt_key: attempted_at,
            },
        )
    except URLError as exc:
        return _persist_channel_update(
            record_path,
            record,
            channel,
            **{
                status_key: "failed",
                error_key: f"URLError: {exc.reason}",
                attempts_key: attempts,
                last_attempt_key: attempted_at,
            },
        )
    except Exception as exc:
        return _persist_channel_update(
            record_path,
            record,
            channel,
            **{
                status_key: "failed",
                error_key: f"{type(exc).__name__}: {exc}",
                attempts_key: attempts,
                last_attempt_key: attempted_at,
            },
        )

    error = ""
    if status_code >= 400:
        error = f"HTTP {status_code}: {response_body}"
    else:
        error = _response_error(response_body)

    return _persist_channel_update(
        record_path,
        record,
        channel,
        **{
            status_key: "sent" if not error else "failed",
            error_key: error,
            attempts_key: attempts,
            last_attempt_key: attempted_at,
        },
    )


def send_feishu_notifications(record_path: Path, settings: Settings) -> None:
    _deliver_channel(record_path, settings, "raw")
    _deliver_channel(record_path, settings, "summary")
