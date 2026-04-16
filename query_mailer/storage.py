from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterator


def ensure_data_dir(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)


def record_path_for(record: dict, data_dir: Path) -> Path:
    timestamp = record["created_at_utc"].replace(":", "").replace("-", "")
    day_prefix = record["created_at_utc"][:10]
    target_dir = data_dir / day_prefix
    ensure_data_dir(target_dir)
    return target_dir / f"{timestamp}_{record['record_id']}.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    ensure_data_dir(path.parent)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def write_record(record: dict, data_dir: Path) -> Path:
    path = record_path_for(record, data_dir)
    _atomic_write_json(path, record)
    return path


def load_record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def update_record(path: Path, **changes: object) -> dict:
    record = load_record(path)
    record.update(changes)
    _atomic_write_json(path, record)
    return record


def iter_record_paths(data_dir: Path) -> Iterator[Path]:
    if not data_dir.exists():
        return iter(())
    paths = sorted(data_dir.rglob("*.json"))
    return iter(paths)
