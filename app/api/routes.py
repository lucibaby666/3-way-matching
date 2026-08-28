import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
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
from app.capabilities.smart_approval import get_smart_approval_system
from app.models.hitl_case import HITLCaseStatus
from app.models.hitl_decision import HITLDecision, HITLDecisionType
from app.monitoring.json_logging import log_event
from app.monitoring.run_history import record_event
from app.storage.factory import create_upload_session_storage
try:
    from database_operations import (
        get_audit_count,
        get_recent_audit_logs,
        insert_audit_to_db,
        verify_database_connection,
    )
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    try:
        from database_operations import (
            get_audit_count,
            get_recent_audit_logs,
            insert_audit_to_db,
            verify_database_connection,
        )
    except ImportError:
        def get_audit_count():
            return 0
        def get_recent_audit_logs(limit=50):
            return []
        def insert_audit_to_db(entry):
            return False
        def verify_database_connection():
            return False, "Database module unavailable"


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


class DemoMatchRequest(BaseModel):
    inject_discrepancy: bool = True


class CreateDecisionRequest(BaseModel):
    decision: str = Field(min_length=1)
    reviewer: str = ""
    comment: str = ""


# ============================================================
# SYSTEM & STATS
# ============================================================


@router.get("/system/stats")
async def get_system_stats() -> dict:
    """Get system stats including ChromaDB precedents count and DB health"""
    smart_approval = get_smart_approval_system()
    db_connected, db_msg = verify_database_connection()
    return {
        "smart_approval": smart_approval.get_stats(),
        "database": {
            "connected": db_connected,
            "message": db_msg,
            "audit_logs_count": get_audit_count() if db_connected else 0,
        },
    }


@router.get("/system/audit-logs")
async def get_audit_logs(limit: int = 50) -> list:
    """Get recent database audit logs"""
    return get_recent_audit_logs(limit=limit)


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


@router.post("/matches/demo", status_code=202)
async def create_demo_match(
    request: Optional[DemoMatchRequest] = None,
    user: UserAccount = Depends(get_current_user),
) -> dict:
    """
    1-Click Demo matching using repository sample documents in data/.
    """
    inject = request.inject_discrepancy if request else True
    upload_id = uuid4().hex
    storage = create_upload_session_storage(upload_id)

    data_dir = Path("data")
    c_path = data_dir / "contracts" / "contract_CON-2026-001.pdf"
    po_path = data_dir / "purchase_orders" / "po_PO-2026-001.pdf"
    inv_path = data_dir / "invoices" / "invoice_INV-2026-001.pdf"

    if c_path.exists():
        storage.write_bytes("contracts/contract_CON-2026-001.pdf", c_path.read_bytes())
    if po_path.exists():
        storage.write_bytes("purchase_orders/po_PO-2026-001.pdf", po_path.read_bytes())
    if inv_path.exists():
        storage.write_bytes("invoices/invoice_INV-2026-001.pdf", inv_path.read_bytes())

    session = UploadSession(
        upload_id=upload_id,
        storage=storage,
        filenames={
            "contracts": ["contract_CON-2026-001.pdf"],
            "purchase_orders": ["po_PO-2026-001.pdf"],
            "invoices": ["invoice_INV-2026-001.pdf"],
        },
    )
    upload_sessions[upload_id] = session

    run = MatchRun(
        run_id=uuid4().hex,
        upload_id=upload_id,
        inject_discrepancy=inject,
    )
    match_runs[run.run_id] = run
    start_match_run(run, session.storage)

    log_event(
        logger,
        "match_started",
        run_id=run.run_id,
        upload_id=run.upload_id,
        inject_discrepancy=inject,
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
# HITL CASE DECISIONS & PRECEDENT LEARNING
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

    existing_case = hitl_service.get_case(case_id)
    if existing_case is None:
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

    # Extract exceptions from validation_result
    exceptions = []
    if getattr(existing_case, "validation_result", None) and getattr(existing_case.validation_result, "exceptions", None):
        exceptions = existing_case.validation_result.exceptions
    elif getattr(existing_case, "exceptions", None):
        exceptions = existing_case.exceptions

    if existing_case.status == HITLCaseStatus.REVIEWED:
        reviewed_case = existing_case
    else:
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

    # ⭐ Store human decision as precedent in ChromaDB for future auto-approval
    smart_approval = get_smart_approval_system()
    precedents_stored = []
    for exc in exceptions:
        exc_dict = {
            "type": str(getattr(exc, "type", "UNKNOWN") or "UNKNOWN"),
            "item_code": getattr(exc, "item_code", "UNKNOWN") or "UNKNOWN",
            "field": str(getattr(exc, "field", "UNKNOWN") or "UNKNOWN"),
            "expected": str(getattr(exc, "expected", "N/A")),
            "actual": str(getattr(exc, "actual", "N/A")),
            "tolerance": str(getattr(exc, "tolerance", "NONE") or "NONE"),
        }
        stored = smart_approval.store_human_decision(
            exception=exc_dict,
            decision=decision_type.value,
            reviewer=reviewer,
            comment=request.comment or f"Decision {decision_type.value} submitted via Web UI",
        )
        precedents_stored.append(stored)

    # Log decision to SQL Server audit table
    try:
        insert_audit_to_db({
            "audit_id": f"HITL-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{reviewed_case.case_id[-6:]}",
            "event_type": f"HITL_DECISION_{decision_type.value}",
            "severity": "INFO",
            "user": reviewer,
            "action": f"Reviewer submitted {decision_type.value} for case {reviewed_case.case_id}",
            "resource": reviewed_case.case_id,
            "resource_type": "HITL_CASE",
            "status": "SUCCESS",
            "error": None,
            "metadata": {
                "case_id": reviewed_case.case_id,
                "decision": decision_type.value,
                "comment": request.comment,
                "precedents_learned": len(precedents_stored)
            }
        })
    except Exception as db_err:
        logger.warning(f"Could not record decision to audit DB: {db_err}")

    record_event(
        {
            "record_type": "decision",
            "case_id": reviewed_case.case_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision_type.value,
            "reviewer": reviewer,
            "precedents_stored": len(precedents_stored),
        }
    )

    log_event(
        logger,
        "hitl_decision_recorded",
        case_id=reviewed_case.case_id,
        decision=decision_type.value,
        reviewer=reviewer,
        precedents_stored=len(precedents_stored),
    )

    decision_val = (
        reviewed_case.decision.decision.value
        if (reviewed_case.decision and hasattr(reviewed_case.decision, "decision"))
        else decision_type.value
    )

    return {
        "case_id": reviewed_case.case_id,
        "status": reviewed_case.status.value,
        "decision": decision_val,
        "reviewer": reviewed_case.reviewer or reviewer,
        "comment": request.comment,
        "precedent_learned": True,
        "chromadb_vectors": smart_approval.get_stats().get("chromadb_vectors", 0),
    }