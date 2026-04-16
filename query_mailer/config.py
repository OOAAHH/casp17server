from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    feishu_webhook: str
    feishu_rejected_webhook: str
    feishu_keyword: str
    secret_token: str
    support_contact_email: str
    data_dir: Path
    max_sequence_length: int
    webhook_timeout_seconds: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        feishu_webhook=os.getenv("FEISHU_WEBHOOK", "").strip(),
        feishu_rejected_webhook=os.getenv("FEISHU_REJECTED_WEBHOOK", "").strip(),
        feishu_keyword=os.getenv("FEISHU_KEYWORD", "").strip(),
        secret_token=os.getenv("SECRET_TOKEN", "").strip(),
        support_contact_email=os.getenv("SUPPORT_CONTACT_EMAIL", "support@example.org").strip(),
        data_dir=Path(os.getenv("DATA_DIR", "data/requests")).expanduser(),
        max_sequence_length=_read_int("MAX_SEQUENCE_LENGTH", 10000),
        webhook_timeout_seconds=_read_int("WEBHOOK_TIMEOUT_SECONDS", 10),
    )
