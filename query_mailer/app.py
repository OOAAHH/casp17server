from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .config import get_settings
from .core import (
    assemble_record,
    notification_snapshot,
    rejected_response_payload,
    render_rejected_text_response,
    render_success_text_response,
    request_has_submission_payload,
    success_response_payload,
    validate_record,
)
from .mailer import send_feishu_notifications
from .storage import update_record, write_record

app = FastAPI(title="Query Mailer")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/", methods=["GET", "POST"])
@app.api_route("/submit", methods=["GET", "POST"])
async def handle_query_mailer(request: Request, background_tasks: BackgroundTasks) -> Response:
    raw_body = await request.body()
    if request.url.path == "/" and not request_has_submission_payload(request, raw_body):
        return PlainTextResponse("Service is running.")

    settings = get_settings()
    record = assemble_record(request, raw_body)
    record_path: Path = write_record(record, settings.data_dir)

    validation = validate_record(record, settings)
    if not validation.accepted:
        updates = {
            "request_status": "rejected",
            "request_error": validation.error,
            "summary_status": "skipped",
            "summary_error": "Summary notifications are only sent for accepted requests.",
            "raw_status": "pending" if settings.feishu_rejected_webhook else "skipped",
            "raw_error": "" if settings.feishu_rejected_webhook else "Raw request webhook is not configured.",
        }
        update_record(
            record_path,
            **updates,
            **notification_snapshot({**record, **updates}),
        )
        if updates["raw_status"] == "pending":
            background_tasks.add_task(send_feishu_notifications, record_path, settings)
        if request.method == "POST":
            return JSONResponse(
                rejected_response_payload({**record, **updates}, settings, validation.error),
                status_code=400,
            )
        return PlainTextResponse(
            render_rejected_text_response({**record, **updates}, settings, validation.error),
            status_code=400,
        )

    updates = {
        "request_status": "accepted",
        "request_error": "",
        "summary_status": "pending" if settings.feishu_webhook else "skipped",
        "summary_error": "" if settings.feishu_webhook else "Accepted summary webhook is not configured.",
        "raw_status": "pending" if settings.feishu_rejected_webhook else "skipped",
        "raw_error": "" if settings.feishu_rejected_webhook else "Raw request webhook is not configured.",
    }
    update_record(
        record_path,
        **updates,
        **notification_snapshot({**record, **updates}),
    )
    if updates["summary_status"] == "pending" or updates["raw_status"] == "pending":
        background_tasks.add_task(send_feishu_notifications, record_path, settings)
    response_record = {**record, **updates}
    if request.method == "POST":
        return JSONResponse(success_response_payload(response_record, settings))
    return PlainTextResponse(render_success_text_response(response_record, settings))
