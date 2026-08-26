import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.pipeline import start_match_run
from app.api.runtime import (
    MatchRun,
    UploadSession,
    hitl_service,
    match_runs,
    upload_sessions,
)
from app.auth.dependencies import (
    UserAccount,
    get_current_user,
    require_admin_or_audit,
)
from app.models.hitl_decision import HITLDecision, HITLDecisionType
from app.monitoring.json_logging import log_event
from app.monitoring.run_history import record_event
from app.storage.factory import create_upload_session_storage

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(require_admin_or_audit)],
)

logger = logging.getLogger(__name__)

UPLOAD_FIELDS = {
    "contract": "contracts",
    "purchase_order": "purchase_orders",
    "invoice": "invoices",
}


class CreateMatchRequest(BaseModel):
    upload_id: str
    inject_discrepancy: bool = False


class CreateDecisionRequest(BaseModel):
    decision: str = Field(min_length=1)
    reviewer: str = ""
    comment: str = ""


# ============================================================
# UPLOADS
# ============================================================


@router.post("/uploads", status_code=201)
async def create_upload(
    contract: List[UploadFile],
    purchase_order: List[UploadFile],
    invoice: List[UploadFile],
) -> dict:
    grouped_files = {
        "contract": contract,
        "purchase_order": purchase_order,
        "invoice": invoice,
    }

    session = UploadSession(
        upload_id=uuid4().hex,
        storage=create_upload_session_storage(),
    )

    saved_documents = []

    for field_name, files in grouped_files.items():
        category = UPLOAD_FIELDS[field_name]

        for file in files:
            filename = file.filename or f"{field_name}.pdf"

            if not filename.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} must be a PDF file.",
                )

            payload = await file.read()

            if not payload:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field_name} file is empty.",
                )

            locator = f"{category}/{filename}"
            handle = session.storage.add_document(
                category=category,
                locator=locator,
                payload=payload,
            )
            saved_documents.append(
                {
                    "category": category,
                    "document_id": handle.document_id,
                    "filename": handle.filename,
                    "size": handle.file_size,
                }
            )

    upload_sessions[session.upload_id] = session

    log_event(
        logger,
        "upload_created",
        upload_id=session.upload_id,
        contract_count=len(contract),
        purchase_order_count=len(purchase_order),
        invoice_count=len(invoice),
    )

    return {
        "id": session.upload_id,
        "documents": saved_documents,
    }


# ============================================================
# MATCH RUNS
# ============================================================


@router.post("/matches", status_code=202)
async def create_match(request: CreateMatchRequest) -> dict:
    session = upload_sessions.get(request.upload_id)

    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Upload not found: {request.upload_id}",
        )

    run = MatchRun(
        run_id=uuid4().hex,
        upload_id=session.upload_id,
        inject_discrepancy=request.inject_discrepancy,
    )
    match_runs[run.run_id] = run

    start_match_run(run, session.storage)

    log_event(
        logger,
        "match_started",
        run_id=run.run_id,
        upload_id=run.upload_id,
        inject_discrepancy=request.inject_discrepancy,
    )

    return {
        "id": run.run_id,
        "status": run.status,
        "upload_id": run.upload_id,
        "events_url": f"/api/matches/{run.run_id}/events",
    }


@router.get("/matches/{run_id}")
async def get_match(run_id: str) -> dict:
    run = _get_run_or_404(run_id)

    return {
        "id": run.run_id,
        "upload_id": run.upload_id,
        "status": run.status,
        "error": run.error,
        "result": run.result,
    }


@router.get("/matches/{run_id}/events")
async def stream_match_events(run_id: str) -> StreamingResponse:
    run = _get_run_or_404(run_id)

    async def event_stream():
        cursor = 0

        while True:
            while cursor < len(run.events):
                event = run.events[cursor]
                cursor += 1

                yield (
                    "data: "
                    + json.dumps(event, default=str)
                    + "\n\n"
                )

                if event["type"] in {"done", "error"}:
                    return

            if run.finished and cursor >= len(run.events):
                return

            await asyncio.sleep(0.2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _get_run_or_404(run_id: str) -> MatchRun:
    run = match_runs.get(run_id)

    if run is None:
        log_event(
            logger,
            "run_not_found",
            level=logging.WARNING,
            run_id=run_id,
            active_run_count=len(match_runs),
        )
        raise HTTPException(
            status_code=404,
            detail=f"Match run not found: {run_id}",
        )

    return run


# ============================================================
# HITL CASE DECISIONS
# ============================================================


@router.post("/cases/{case_id}/decisions", status_code=201)
async def create_decision(
    case_id: str,
    request: CreateDecisionRequest,
    user: UserAccount = Depends(get_current_user),
) -> dict:
    reviewer = request.reviewer.strip() or user.username

    try:
        decision_type = HITLDecisionType(request.decision)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                "Invalid decision. "
                f"Allowed values: {[item.value for item in HITLDecisionType]}."
            ),
        )

    if hitl_service.get_case(case_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"HITL case not found: {case_id}",
        )

    decision = HITLDecision(
        decision=decision_type,
        reviewer=reviewer,
        comment=request.comment,
        timestamp=datetime.now(timezone.utc),
    )

    try:
        reviewed_case = await asyncio.to_thread(
            hitl_service.apply_decision,
            case_id,
            decision,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )

    record_event(
        {
            "record_type": "decision",
            "case_id": reviewed_case.case_id,
            "timestamp": datetime.now(timezone.utc)
            .isoformat(),
            "decision": decision_type.value,
            "reviewer": reviewer,
        }
    )

    log_event(
        logger,
        "hitl_decision_recorded",
        case_id=reviewed_case.case_id,
        decision=decision_type.value,
        reviewer=reviewer,
    )

    return {
        "case_id": reviewed_case.case_id,
        "status": reviewed_case.status.value,
        "decision": reviewed_case.decision.decision.value,
        "reviewer": reviewed_case.reviewer,
    }