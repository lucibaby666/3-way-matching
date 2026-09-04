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
    persist_run,
    persist_session,
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
from app.persistence.store import persistence_store
from app.storage.factory import (
    create_document_storage,
    create_upload_session_storage,
)
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


class AzureMatchRequest(BaseModel):
    contract_locators: Optional[List[str]] = None
    po_locators: Optional[List[str]] = None
    invoice_locators: Optional[List[str]] = None


class DemoMatchRequest(BaseModel):
    pass


class CreateDecisionRequest(BaseModel):
    decision: str = Field(min_length=1)
    reason: str = Field(min_length=1)
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

    persist_session(session)

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
        inject_discrepancy=False,
    )
    persist_run(run)

    start_match_run(run, session.storage)

    log_event(
        logger,
        "match_started",
        run_id=run.run_id,
        upload_id=run.upload_id,
    )

    return {
        "id": run.run_id,
        "status": run.status,
        "upload_id": run.upload_id,
        "events_url": f"/api/matches/{run.run_id}/events",
    }


@router.post("/matches/azure", status_code=202)
async def create_azure_match(
    request: Optional[AzureMatchRequest] = None,
) -> dict:
    """
    Run matching directly from files in Azure Blob Storage.

    Lists documents from the configured container's
    contracts/, purchase_orders/, invoices/ folders.
    Optionally filter by providing specific locators.
    """
    contract_locs = request.contract_locators if request else None
    po_locs = request.po_locators if request else None
    inv_locs = request.invoice_locators if request else None

    try:
        from app.storage.azure_blob_document_storage import (
            AzureBlobDocumentStorage,
        )

        azure_storage = AzureBlobDocumentStorage.from_env()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Azure Blob Storage is not configured: {exc}",
        )

    from app.storage.filtered_document_storage import (
        FilteredDocumentStorage,
    )

    allowed = {}
    if contract_locs is not None:
        allowed["contracts"] = contract_locs
    if po_locs is not None:
        allowed["purchase_orders"] = po_locs
    if inv_locs is not None:
        allowed["invoices"] = inv_locs

    if allowed:
        storage = FilteredDocumentStorage(
            backend=azure_storage,
            allowed_locators=allowed,
        )
    else:
        storage = azure_storage

    from app.capabilities.document_intake import DocumentIntake
    intake = DocumentIntake(storage=storage)
    discovered = intake.discover_documents()

    if not discovered.get("contracts"):
        raise HTTPException(
            status_code=422,
            detail="No contract documents found in Azure Blob Storage.",
        )
    if not discovered.get("purchase_orders"):
        raise HTTPException(
            status_code=422,
            detail="No purchase order documents found in Azure Blob Storage.",
        )
    if not discovered.get("invoices"):
        raise HTTPException(
            status_code=422,
            detail="No invoice documents found in Azure Blob Storage.",
        )

    upload_id = uuid4().hex
    session = UploadSession(
        upload_id=upload_id,
        storage=storage,
    )
    persist_session(session)

    documents_snapshot = {
        cat: [d.get("filename", "") for d in docs]
        for cat, docs in discovered.items()
    }

    run = MatchRun(
        run_id=uuid4().hex,
        upload_id=upload_id,
        inject_discrepancy=False,
        source_type="azure_blob",
        documents_snapshot=documents_snapshot,
    )
    persist_run(run)

    start_match_run(run, storage)

    log_event(
        logger,
        "azure_match_started",
        run_id=run.run_id,
        upload_id=upload_id,
        contract_count=len(discovered.get("contracts", [])),
        po_count=len(discovered.get("purchase_orders", [])),
        invoice_count=len(discovered.get("invoices", [])),
    )

    return {
        "id": run.run_id,
        "status": run.status,
        "upload_id": upload_id,
        "source": "azure_blob",
        "events_url": f"/api/matches/{run.run_id}/events",
        "documents": {
            cat: [d.get("filename", "") for d in docs]
            for cat, docs in discovered.items()
        },
    }


@router.post("/matches/demo", status_code=202)
async def create_demo_match(
    request: Optional[DemoMatchRequest] = None,
    user: UserAccount = Depends(get_current_user),
) -> dict:
    """
    1-Click Demo matching using repository sample documents in data/.
    """
    upload_id = uuid4().hex
    storage = create_upload_session_storage()

    data_dir = Path("data")
    c_path = data_dir / "contracts" / "contract_CON-2026-001.pdf"
    po_path = data_dir / "purchase_orders" / "po_PO-2026-001.pdf"
    inv_path = data_dir / "invoices" / "invoice_INV-2026-001.pdf"

    if c_path.exists():
        storage.add_document("contracts", "contracts/contract_CON-2026-001.pdf", c_path.read_bytes())
    if po_path.exists():
        storage.add_document("purchase_orders", "purchase_orders/po_PO-2026-001.pdf", po_path.read_bytes())
    if inv_path.exists():
        storage.add_document("invoices", "invoices/invoice_INV-2026-001.pdf", inv_path.read_bytes())

    session = UploadSession(
        upload_id=upload_id,
        storage=storage,
        filenames={
            "contracts": ["contract_CON-2026-001.pdf"],
            "purchase_orders": ["po_PO-2026-001.pdf"],
            "invoices": ["invoice_INV-2026-001.pdf"],
        },
    )
    persist_session(session)

    run = MatchRun(
        run_id=uuid4().hex,
        upload_id=upload_id,
        inject_discrepancy=False,
        source_type="demo",
    )
    persist_run(run)
    start_match_run(run, storage)

    log_event(
        logger,
        "match_started",
        run_id=run.run_id,
        upload_id=run.upload_id,
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
# RUN HISTORY (PERSISTED)
# ============================================================


@router.get("/runs")
async def list_runs(limit: int = 50) -> list:
    """List recent match runs from Azure SQL."""
    runs = persistence_store.get_runs(limit=limit)
    return runs


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str) -> dict:
    """Get full match run detail including result payload."""
    run = persistence_store.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=f"Run not found: {run_id}",
        )
    if run.get("result") and isinstance(run["result"], str):
        try:
            run["result"] = json.loads(run["result"])
        except (json.JSONDecodeError, TypeError):
            pass
    return run


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str) -> list:
    """Get persisted events for a run (for replay/history)."""
    events = persistence_store.get_events(run_id)
    return events


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

    if not request.reason.strip():
        raise HTTPException(
            status_code=422,
            detail="A reason is required for all HITL decisions (approve, reject, or override).",
        )

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
        reason=request.reason.strip(),
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

    # Store human decision as precedent in ChromaDB for future auto-approval
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
            "action": f"Reviewer submitted {decision_type.value} for case {reviewed_case.case_id}. Reason: {request.reason}",
            "resource": reviewed_case.case_id,
            "resource_type": "HITL_CASE",
            "status": "SUCCESS",
            "error": None,
            "metadata": {
                "case_id": reviewed_case.case_id,
                "decision": decision_type.value,
                "reason": request.reason,
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
            "reason": request.reason,
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
        reason=request.reason,
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
        "reason": request.reason,
        "reviewer": reviewed_case.reviewer or reviewer,
        "comment": request.comment,
        "precedent_learned": True,
        "chromadb_vectors": smart_approval.get_stats().get("chromadb_vectors", 0),
    }
