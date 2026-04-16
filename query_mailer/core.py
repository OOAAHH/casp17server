from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote_plus

from fastapi import Request

from .config import Settings

SEQUENCE_RE = re.compile(r"^[A-Za-z]+$")
FIELD_ALIASES = {
    "sequence": ["sequence", "SEQUENCE"],
    "target": ["target", "TARGET"],
    "reply_email": ["reply_email", "REPLY_EMAIL", "email", "EMAIL", "gzlab", "GZLAB"],
    "token": ["token", "TOKEN"],
    "stoichiometry": ["stoichiometry", "STOICHIOMETRY"],
}
MALFORMED_BARE_ALIASES = sorted(
    {alias for aliases in FIELD_ALIASES.values() for alias in aliases},
    key=len,
    reverse=True,
)


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    error: str


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _decode_param_piece(value: str) -> str:
    return unquote_plus(value)


def _split_param_segment(segment: str) -> tuple[str, str]:
    if "=" in segment:
        key, value = segment.split("=", 1)
        return _decode_param_piece(key), _decode_param_piece(value)

    decoded = _decode_param_piece(segment)
    for alias in MALFORMED_BARE_ALIASES:
        if decoded.startswith(alias) and decoded != alias:
            # Support legacy malformed fragments such as "targetTargetName".
            return alias, decoded[len(alias) :]
    return decoded, ""


def normalize_sequence_value(value: str) -> str:
    normalized_newlines = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    stripped = normalized_newlines.strip()
    if not stripped:
        return ""

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if lines and lines[0].startswith(">"):
        lines = lines[1:]

    return "".join(lines)


def parse_params(raw_text: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for segment in raw_text.split("&"):
        if not segment:
            continue
        key, value = _split_param_segment(segment)
        if not key:
            continue
        if key in merged:
            current = merged[key]
            if isinstance(current, list):
                current.append(value)
            else:
                merged[key] = [current, value]
        else:
            merged[key] = value
    return merged


def pick_alias(params: dict[str, Any], aliases: list[str]) -> str:
    for alias in aliases:
        if alias not in params:
            continue
        value = params[alias]
        if isinstance(value, list):
            return str(value[-1]).strip()
        return str(value).strip()
    return ""


def normalized_params(all_params: dict[str, Any]) -> dict[str, str]:
    normalized = {name: pick_alias(all_params, aliases) for name, aliases in FIELD_ALIASES.items()}
    normalized["sequence"] = normalize_sequence_value(normalized.get("sequence", ""))
    return normalized


def request_has_submission_payload(request: Request, raw_body: bytes) -> bool:
    return bool(request.url.query or raw_body or request.url.path == "/submit")


def client_ip_for_request(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


def assemble_record(request: Request, raw_body: bytes) -> dict[str, Any]:
    raw_body_text = decode_body(raw_body)
    query_params = parse_params(request.url.query)
    body_params = parse_params(raw_body_text)
    all_params = {**query_params, **body_params}
    normalized = normalized_params(all_params)
    sequence = normalized.get("sequence", "")

    return {
        "record_id": uuid.uuid4().hex,
        "created_at_utc": utc_now_text(),
        "method": request.method,
        "path": request.url.path,
        "full_url": str(request.url),
        "raw_query": request.url.query,
        "decoded_query": unquote_plus(request.url.query),
        "raw_body": raw_body_text,
        "client_ip": client_ip_for_request(request),
        "user_agent": request.headers.get("user-agent", ""),
        "headers": {
            "host": request.headers.get("host", ""),
            "content_type": request.headers.get("content-type", ""),
            "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
            "x_forwarded_proto": request.headers.get("x-forwarded-proto", ""),
        },
        "all_params": all_params,
        "normalized_params": normalized,
        "sequence_length": len(sequence),
        "request_status": "received",
        "request_error": "",
        "summary_status": "not_attempted",
        "summary_error": "",
        "summary_attempts": 0,
        "last_summary_attempt_at_utc": "",
        "raw_status": "not_attempted",
        "raw_error": "",
        "raw_attempts": 0,
        "last_raw_attempt_at_utc": "",
        "mail_status": "not_attempted",
        "mail_error": "",
        "mail_attempts": 0,
        "last_mail_attempt_at_utc": "",
    }


def validate_record(record: dict[str, Any], settings: Settings) -> ValidationResult:
    normalized = record["normalized_params"]
    sequence = normalized.get("sequence", "")
    token = normalized.get("token", "")

    if not sequence:
        return ValidationResult(False, "Missing sequence.")
    if len(sequence) > settings.max_sequence_length:
        return ValidationResult(False, f"Sequence is too long (>{settings.max_sequence_length}).")
    if not SEQUENCE_RE.fullmatch(sequence):
        return ValidationResult(False, "Sequence must contain only letters A-Z.")
    if settings.secret_token and token != settings.secret_token:
        return ValidationResult(False, "Invalid token.")
    return ValidationResult(True, "")


def notification_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    relevant_prefixes = [
        prefix
        for prefix in ("summary", "raw")
        if record.get(f"{prefix}_status", "") not in {"", "not_attempted"}
    ]

    statuses = [str(record.get(f"{prefix}_status", "")) for prefix in relevant_prefixes]
    if not statuses:
        mail_status = "not_attempted"
    elif any(status == "failed" for status in statuses):
        mail_status = "failed"
    elif any(status == "pending" for status in statuses):
        mail_status = "pending"
    elif all(status == "skipped" for status in statuses):
        mail_status = "skipped"
    elif all(status in {"sent", "skipped"} for status in statuses):
        mail_status = "sent"
    else:
        mail_status = "not_attempted"

    errors: list[str] = []
    if mail_status == "failed":
        for prefix in relevant_prefixes:
            if record.get(f"{prefix}_status") == "failed" and record.get(f"{prefix}_error"):
                errors.append(f"{prefix}: {record[f'{prefix}_error']}")
    elif mail_status == "skipped":
        for prefix in relevant_prefixes:
            if record.get(f"{prefix}_status") == "skipped" and record.get(f"{prefix}_error"):
                errors.append(f"{prefix}: {record[f'{prefix}_error']}")

    timestamps = [
        str(record.get(f"last_{prefix}_attempt_at_utc", ""))
        for prefix in relevant_prefixes
        if record.get(f"last_{prefix}_attempt_at_utc")
    ]

    return {
        "mail_status": mail_status,
        "mail_error": " | ".join(errors),
        "mail_attempts": sum(int(record.get(f"{prefix}_attempts", 0)) for prefix in relevant_prefixes),
        "last_mail_attempt_at_utc": max(timestamps) if timestamps else "",
    }


def render_feishu_summary_message(record: dict[str, Any], settings: Settings) -> str:
    normalized = record["normalized_params"]
    lines = []
    if settings.feishu_keyword:
        lines.append(settings.feishu_keyword)
    lines.extend(
        [
            "Accepted query received",
            f"target: {normalized.get('target', '')}",
            f"reply_email: {normalized.get('reply_email', '')}",
            f"stoichiometry: {normalized.get('stoichiometry', '')}",
            f"time_utc: {record['created_at_utc']}",
            f"method: {record['method']}",
            f"sequence: {normalized.get('sequence', '')}",
            f"sequence_length: {record['sequence_length']}",
        ]
    )
    return "\n".join(lines)


def render_feishu_raw_message(record: dict[str, Any], settings: Settings) -> str:
    normalized = record["normalized_params"]
    request_status = record.get("request_status", "")
    title = "Raw request received"
    submitted_sequence_raw = ""
    for alias in FIELD_ALIASES["sequence"]:
        if alias in record["all_params"]:
            submitted_sequence_raw = str(record["all_params"][alias])
            break
    lines = []
    if settings.feishu_keyword:
        lines.append(settings.feishu_keyword)
    lines.extend(
        [
            title,
            f"request_status: {request_status}",
            f"request_error: {record.get('request_error', '')}",
            f"method: {record['method']}",
            f"path: {record['path']}",
            f"target: {normalized.get('target', '')}",
            f"reply_email: {normalized.get('reply_email', '')}",
            f"time_utc: {record['created_at_utc']}",
            f"client_ip: {record['client_ip']}",
            f"user_agent: {record['user_agent']}",
            f"submitted_sequence_raw: {submitted_sequence_raw}",
            f"normalized_sequence: {normalized.get('sequence', '')}",
            f"sequence_length: {record['sequence_length']}",
            "",
            "full_url:",
            record["full_url"],
            "",
            "raw_query:",
            record["raw_query"],
            "",
            "decoded_query:",
            record["decoded_query"],
            "",
            "all_params_json:",
            json.dumps(record["all_params"], ensure_ascii=False, indent=2, sort_keys=True),
        ]
    )
    return "\n".join(lines)


def render_success_text_response(record: dict[str, Any], settings: Settings) -> str:
    normalized = record["normalized_params"]
    lines = [
        "OK",
        "Request accepted.",
        f"Received at (UTC): {record['created_at_utc']}",
    ]
    if normalized.get("target"):
        lines.append(f"Target: {normalized['target']}")
    lines.append(f"Sequence length: {record['sequence_length']}")
    lines.append(f"If there are any questions, contact: {settings.support_contact_email}")
    return "\n".join(lines)


def render_rejected_text_response(record: dict[str, Any], settings: Settings, reason: str) -> str:
    normalized = record["normalized_params"]
    lines = [
        "Request rejected.",
        f"Reason: {reason}",
        f"Received at (UTC): {record['created_at_utc']}",
    ]
    if normalized.get("target"):
        lines.append(f"Target: {normalized['target']}")
    lines.append(f"If there are any questions, contact: {settings.support_contact_email}")
    return "\n".join(lines)


def success_response_payload(record: dict[str, Any], settings: Settings) -> dict[str, Any]:
    normalized = record["normalized_params"]
    return {
        "ok": True,
        "request_status": "accepted",
        "message": "Request accepted.",
        "reason": "",
        "received_at_utc": record["created_at_utc"],
        "target": normalized.get("target", ""),
        "reply_email": normalized.get("reply_email", ""),
        "sequence_length": record["sequence_length"],
        "contact_email": settings.support_contact_email,
    }


def rejected_response_payload(record: dict[str, Any], settings: Settings, reason: str) -> dict[str, Any]:
    normalized = record["normalized_params"]
    return {
        "ok": False,
        "request_status": "rejected",
        "message": "Request rejected.",
        "reason": reason,
        "received_at_utc": record["created_at_utc"],
        "target": normalized.get("target", ""),
        "reply_email": normalized.get("reply_email", ""),
        "sequence_length": record["sequence_length"],
        "contact_email": settings.support_contact_email,
    }
