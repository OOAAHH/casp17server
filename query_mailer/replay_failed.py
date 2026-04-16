from __future__ import annotations

import argparse

from .config import get_settings
from .mailer import send_feishu_notifications
from .storage import iter_record_paths, load_record


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay failed or pending Query Mailer notifications.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of records to retry.")
    args = parser.parse_args()

    settings = get_settings()
    replayed = 0
    for path in iter_record_paths(settings.data_dir):
        if replayed >= args.limit:
            break
        record = load_record(path)
        if record.get("request_status") not in {"accepted", "rejected"}:
            continue
        summary_status = record.get("summary_status", "")
        raw_status = record.get("raw_status", "")
        legacy_status = record.get("mail_status", "")
        if (
            summary_status not in {"pending", "failed"}
            and raw_status not in {"pending", "failed"}
            and legacy_status not in {"pending", "failed"}
        ):
            continue
        send_feishu_notifications(path, settings)
        replayed += 1

    print(f"replayed={replayed}")


if __name__ == "__main__":
    main()
