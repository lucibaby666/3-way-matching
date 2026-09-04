import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.runtime import MatchRun
from app.capabilities.document_set_loader import (
    DocumentSetLoader,
)
from app.persistence.store import persistence_store
from app.capabilities.document_snip import DocumentSnip
from app.capabilities.evidence_generator import (
    EvidenceGenerator,
)
from app.capabilities.smart_approval import get_smart_approval_system
from app.matching.matching_engine import MatchingEngine
from app.models.validation_result import ValidationResult
from app.monitoring.json_logging import log_event
from app.monitoring.run_history import record_event
from app.storage.document_storage import DocumentStorage
try:
    from database_operations import (
        insert_audit_to_db,
        insert_statistics_to_db,
    )
except ImportError:
    import sys
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    try:
        from database_operations import (
            insert_audit_to_db,
            insert_statistics_to_db,
        )
    except ImportError:
        def insert_audit_to_db(entry):
            return False
        def insert_statistics_to_db(stats):
            return None


EVIDENCE_ROOT = Path("outputs/evidence")

logger = logging.getLogger(__name__)

LINE_FIELDS = (
    "item_code",
    "description",
    "quantity",
    "unit_price",
    "amount",
)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(
        value, (str, int, float, bool)
    ):
        return value
    return str(value)


def _line_items_as_dicts(line_items: List[Any]) -> List[Dict[str, Any]]:
    return [
        {
            field: _json_safe(getattr(item, field, None))
            for field in LINE_FIELDS
        }
        for item in line_items
    ]


def _snip_url(snip_path: str) -> str:
    try:
        relative = Path(snip_path).relative_to(EVIDENCE_ROOT)
    except ValueError:
        relative = Path(snip_path).name
    return f"/evidence/{relative.as_posix()}"


def _exception_as_dict(exception: Any, approval_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "type": str(exception.type),
        "item_code": exception.item_code,
        "field": exception.field,
        "expected": _json_safe(exception.expected),
        "actual": _json_safe(exception.actual),
    }

    if getattr(exception, "tolerance", None) is not None:
        data["tolerance"] = str(exception.tolerance)

    if exception.evidence:
        data["evidence"] = [
            {
                **evidence,
                "snip_url": _snip_url(evidence["snip_path"]),
            }
            for evidence in exception.evidence
            if evidence.get("snip_path")
        ]

    if approval_info:
        data["auto_approved"] = approval_info.get("auto_approved", False)
        data["decision"] = approval_info.get("decision")
        data["similarity_score"] = approval_info.get("similarity_score")
        data["precedent_id"] = approval_info.get("precedent_id")
        data["reviewer"] = approval_info.get("reviewer")
        data["comment"] = approval_info.get("comment")

    return data


async def execute_match_run(
    run: MatchRun,
    storage: DocumentStorage,
) -> None:
    """
    Run the full 3-way matching pipeline with Smart Approval and ChromaDB precedent checking.
    """

    def step(step_name: str, message: str) -> None:
        icons = {
            "intake": "📥 [INTAKE]",
            "matching": "🔍 [MATCHING]",
            "smart-approval": "🧠 [SMART APPROVAL]",
            "hitl": "👤 [HUMAN IN THE LOOP]",
        }
        icon = icons.get(step_name, f"🔹 [{step_name.upper()}]")
        print(f"{icon} {message}", flush=True)

        logger.info(
            "Match run %s [%s]: %s",
            run.run_id,
            step_name,
            message,
        )
        log_event(
            logger,
            "pipeline_step",
            run_id=run.run_id,
            upload_id=run.upload_id,
            step=step_name,
            message=message,
        )
        run.emit(
            {
                "type": "step",
                "step": step_name,
                "message": message,
            }
        )

    started_at = datetime.now(timezone.utc)
    durations_ms: Dict[str, float] = {}
    phase_start = time.perf_counter()
    total_start = phase_start

    def mark_phase(phase_name: str) -> None:
        nonlocal phase_start
        now = time.perf_counter()
        durations_ms[phase_name] = round(
            (now - phase_start) * 1000, 1
        )
        phase_start = now

    try:
        run.status = "running"

        # Log system start to DB
        insert_audit_to_db({
            "audit_id": f"SYS-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run.run_id[:6]}",
            "event_type": "SYSTEM_START",
            "severity": "INFO",
            "user": "system",
            "action": f"Starting 3-Way Matching Run {run.run_id}",
            "resource": run.run_id,
            "resource_type": "RUN",
            "status": "RUNNING",
            "error": None,
            "metadata": {
                "run_id": run.run_id,
                "upload_id": run.upload_id,
                "inject_discrepancy": run.inject_discrepancy
            }
        })

        # --------------------------------------------------
        # 1. INTAKE & EXTRACTION
        # --------------------------------------------------

        step("intake", "Initiating parallel document extraction with Azure Document Intelligence...")

        loader = DocumentSetLoader(storage=storage)
        loaded = await asyncio.to_thread(loader.load)
        mark_phase("intake")

        documents = loaded["documents"]
        contracts = loaded["contracts"]
        purchase_orders = loaded["purchase_orders"]
        invoices = loaded["invoices"]

        step(
            "intake",
            f"Successfully extracted {len(contracts)} contract(s), "
            f"{len(purchase_orders)} PO(s), "
            f"{len(invoices)} invoice(s).",
        )

        insert_audit_to_db({
            "audit_id": f"DOC-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run.run_id[:6]}",
            "event_type": "DOCUMENT_INTAKE_COMPLETE",
            "severity": "INFO",
            "user": "system",
            "action": "Document intake completed",
            "resource": run.upload_id,
            "resource_type": "UPLOAD",
            "status": "SUCCESS",
            "error": None,
            "metadata": {
                "contracts": len(contracts),
                "purchase_orders": len(purchase_orders),
                "invoices": len(invoices)
            }
        })

        # --------------------------------------------------
        # 2. DETERMINISTIC MATCHING + EVIDENCE
        # --------------------------------------------------

        step("matching", "Running deterministic matching engine.")

        evidence_dir = EVIDENCE_ROOT / run.run_id
        evidence_generator = EvidenceGenerator(
            document_snip=DocumentSnip(storage=storage),
            output_dir=str(evidence_dir),
        )
        engine = MatchingEngine(
            evidence_generator=evidence_generator
        )
        result = await asyncio.to_thread(
            engine.match_many,
            contracts,
            purchase_orders,
            invoices,
        )
        mark_phase("matching")

        step(
            "matching",
            f"Deterministic status: {result.status} with {len(result.exceptions)} exception(s).",
        )

        insert_audit_to_db({
            "audit_id": f"MATCH-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run.run_id[:6]}",
            "event_type": "MATCHING_COMPLETE",
            "severity": "INFO",
            "user": "system",
            "action": f"Matching completed with status: {result.status}",
            "resource": run.run_id,
            "resource_type": "MATCHING",
            "status": result.status,
            "error": None,
            "metadata": {
                "matching_status": result.status,
                "exception_count": len(result.exceptions)
            }
        })

        # --------------------------------------------------
        # 4. SMART APPROVAL (CHROMADB PRECEDENT EVALUATION)
        # --------------------------------------------------

        smart_approval = get_smart_approval_system()
        exception_evaluations: List[Dict[str, Any]] = []
        auto_approved_exceptions: List[Any] = []
        human_review_exceptions: List[Any] = []

        if result.exceptions:
            step("smart-approval", "Querying ChromaDB for historical exception precedents...")

            for exception in result.exceptions:
                exc_dict = {
                    "type": str(exception.type),
                    "item_code": exception.item_code or "UNKNOWN",
                    "field": str(exception.field) or "UNKNOWN",
                    "expected": str(exception.expected),
                    "actual": str(exception.actual),
                    "tolerance": str(getattr(exception, "tolerance", "NONE") or "NONE"),
                }

                eval_result = await asyncio.to_thread(
                    smart_approval.process_exception, exc_dict
                )
                exception_evaluations.append(eval_result)

                if eval_result.get("auto_approved"):
                    auto_approved_exceptions.append(exception)
                    similarity_pct = round(eval_result['similarity_score'] * 100, 1)
                    step(
                        "smart-approval",
                        f"🤖 Auto-{eval_result['decision']}: {exception.type} on {exception.item_code} "
                        f"({similarity_pct}% similarity to precedent {eval_result['precedent_id']})."
                    )
                else:
                    human_review_exceptions.append(exception)
                    step(
                        "smart-approval",
                        f"👤 No precedent match for {exception.type} on {exception.item_code} — Routing to Human Review."
                    )

        mark_phase("smart_approval")

        # --------------------------------------------------
        # 5. HITL ROUTING
        # --------------------------------------------------

        from app.api.runtime import hitl_service

        hitl_case = None

        if human_review_exceptions:
            # Create HITL case only for unresolved exceptions
            unresolved_validation_result = ValidationResult(
                status="EXCEPTION",
                exceptions=human_review_exceptions,
            )
            hitl_case = await asyncio.to_thread(
                hitl_service.create_case,
                unresolved_validation_result,
            )
            step(
                "hitl",
                f"Case {hitl_case.case_id} created for {len(human_review_exceptions)} unresolved exception(s).",
            )

        elif auto_approved_exceptions and not human_review_exceptions:
            step(
                "hitl",
                "All exceptions were auto-approved based on historical precedents! No human review needed.",
            )
        else:
            step(
                "hitl",
                "No exceptions routed to human review.",
            )

        mark_phase("hitl_routing")

        # Determine overall effective status
        effective_status = result.status
        if result.exceptions and len(auto_approved_exceptions) == len(result.exceptions):
            effective_status = "AUTO_APPROVED"
        elif human_review_exceptions:
            effective_status = "EXCEPTION"

        # --------------------------------------------------
        # 6. BUILD RESULT PAYLOAD
        # --------------------------------------------------

        first = lambda category: (
            loaded["documents"][category][0]
            if loaded["documents"].get(category)
            else {}
        )  # noqa: E731

        formatted_exceptions = [
            _exception_as_dict(
                exc,
                approval_info=exception_evaluations[i] if i < len(exception_evaluations) else None
            )
            for i, exc in enumerate(result.exceptions)
        ]

        payload: Dict[str, Any] = {
            "status": effective_status,
            "deterministic_status": result.status,
            "documents": {
                "contracts": {
                    "number": contracts[0].contract_number
                    if contracts
                    else None,
                    "filename": first("contracts").get("filename"),
                },
                "purchase_orders": {
                    "number": purchase_orders[0].po_number
                    if purchase_orders
                    else None,
                    "filename": first("purchase_orders").get(
                        "filename"
                    ),
                },
                "invoices": {
                    "number": invoices[0].invoice_number
                    if invoices
                    else None,
                    "filename": first("invoices").get("filename"),
                },
            },
            "line_items": {
                "contracts": _line_items_as_dicts(
                    contracts[0].line_items if contracts else []
                ),
                "purchase_orders": _line_items_as_dicts(
                    purchase_orders[0].line_items
                    if purchase_orders
                    else []
                ),
                "invoices": _line_items_as_dicts(
                    invoices[0].line_items if invoices else []
                ),
            },
            "exceptions": formatted_exceptions,
            "smart_approval": {
                "total_exceptions": len(result.exceptions),
                "auto_approved_count": len(auto_approved_exceptions),
                "human_review_count": len(human_review_exceptions),
                "stats": smart_approval.get_stats(),
            },
            "hitl_case": {
                "case_id": hitl_case.case_id,
                "status": hitl_case.status.value,
                "evidence_count": len(hitl_case.evidence),
            }
            if hitl_case is not None
            else None,
        }

        step(
            "done-preparing",
            f"Pipeline finished with status: {effective_status}.",
        )

        run.result = payload
        run.emit({"type": "done", "payload": payload})

        try:
            persistence_store.update_run_status(
                run.run_id, "completed", result=payload
            )
        except Exception:
            pass

        _record_run(
            run=run,
            started_at=started_at,
            durations_ms=durations_ms,
            total_start=total_start,
            outcome="completed",
            result=result,
            documents=documents,
            hitl_case_id=(
                hitl_case.case_id
                if hitl_case is not None
                else None
            ),
            error=None,
        )

        # Log completion to DB
        insert_audit_to_db({
            "audit_id": f"SYS-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run.run_id[:6]}",
            "event_type": "SYSTEM_COMPLETE",
            "severity": "INFO",
            "user": "system",
            "action": f"Run completed with status {effective_status}",
            "resource": run.run_id,
            "resource_type": "RUN",
            "status": "SUCCESS",
            "error": None,
            "metadata": {
                "run_id": run.run_id,
                "status": effective_status,
                "auto_approved": len(auto_approved_exceptions),
                "human_reviewed": len(human_review_exceptions),
                "hitl_case_id": hitl_case.case_id if hitl_case else None
            }
        })

        # Insert statistics into SQL Server table
        try:
            insert_statistics_to_db({
                "total_entries": len(result.exceptions),
                "severity_counts": {
                    "INFO": len(auto_approved_exceptions),
                    "WARNING": len(human_review_exceptions),
                    "HIGH": 0,
                    "CRITICAL": 0
                },
                "status_counts": {
                    "SUCCESS": 1 if effective_status in ["PASS", "AUTO_APPROVED"] else 0,
                    "FAILED": 1 if effective_status == "EXCEPTION" else 0
                },
                "matching_status": effective_status,
                "exception_count": len(result.exceptions),
                "hitl_case_id": hitl_case.case_id if hitl_case else None,
                "evidence_dir": str(evidence_dir)
            })
        except Exception as stats_err:
            logger.warning(f"Failed to record statistics to DB: {stats_err}")

        print("\n" + "=" * 70, flush=True)
        print(f"✅ MATCH RUN COMPLETED: {run.run_id}", flush=True)
        print(f"   Status: {effective_status}", flush=True)
        print(f"   Contracts: {len(contracts)} | POs: {len(purchase_orders)} | Invoices: {len(invoices)}", flush=True)
        print(f"   Total Exceptions: {len(result.exceptions)}", flush=True)
        print(f"   Auto-Approved via ChromaDB: {len(auto_approved_exceptions)}", flush=True)
        print(f"   Pending Human Review: {len(human_review_exceptions)}", flush=True)
        print("=" * 70 + "\n", flush=True)

        log_event(
            logger,
            "run_completed",
            run_id=run.run_id,
            upload_id=run.upload_id,
            status=effective_status,
            exception_count=len(result.exceptions),
            auto_approved_count=len(auto_approved_exceptions),
            hitl_created=hitl_case is not None,
            duration_ms=durations_ms.get("total"),
            inject_discrepancy=run.inject_discrepancy,
        )

    except Exception as error:
        logger.exception(
            "Match run %s failed (completed phases: %s)",
            run.run_id,
            list(durations_ms.keys()) or "none",
        )
        log_event(
            logger,
            "run_failed",
            level=logging.ERROR,
            run_id=run.run_id,
            upload_id=run.upload_id,
            error_type=type(error).__name__,
            error_message=str(error),
            completed_phases=list(durations_ms.keys()),
            inject_discrepancy=run.inject_discrepancy,
        )
        insert_audit_to_db({
            "audit_id": f"ERR-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run.run_id[:6]}",
            "event_type": "SYSTEM_ERROR",
            "severity": "CRITICAL",
            "user": "system",
            "action": f"Run failed: {error}",
            "resource": run.run_id,
            "resource_type": "RUN",
            "status": "FAILED",
            "error": str(error),
            "metadata": {"traceback": str(error)}
        })
        run.emit(
            {
                "type": "error",
                "message": str(error) or error.__class__.__name__,
            }
        )

        try:
            persistence_store.update_run_status(
                run.run_id, "failed",
                error=str(error) or error.__class__.__name__,
            )
        except Exception:
            pass

        _record_run(
            run=run,
            started_at=started_at,
            durations_ms=durations_ms,
            total_start=total_start,
            outcome="failed",
            result=None,
            documents=None,
            hitl_case_id=None,
            error=str(error) or error.__class__.__name__,
        )



def _record_run(
    run: MatchRun,
    started_at: datetime,
    durations_ms: Dict[str, float],
    total_start: float,
    outcome: str,
    result: Any,
    documents: Dict[str, List[Any]] | None,
    hitl_case_id: str | None,
    error: str | None,
) -> None:
    """
    Append one monitoring record for this run. Monitoring
    failures must never break the pipeline.
    """

    try:
        durations_ms = dict(durations_ms)
        durations_ms["total"] = round(
            (time.perf_counter() - total_start) * 1000, 1
        )

        exception_types: Dict[str, int] = {}

        if result is not None:
            for exception in result.exceptions:
                exception_types[exception.type] = (
                    exception_types.get(exception.type, 0)
                    + 1
                )

        record_event(
            {
                "record_type": "run",
                "run_id": run.run_id,
                "upload_id": run.upload_id,
                "timestamp": datetime.now(timezone.utc)
                .isoformat(),
                "outcome": outcome,
                "status": (
                    result.status
                    if result is not None
                    and outcome == "completed"
                    else None
                ),
                "exception_count": sum(
                    exception_types.values()
                ),
                "exception_types": exception_types,
                "hitl_created": hitl_case_id is not None,
                "case_id": hitl_case_id,
                "durations_ms": durations_ms,
                "documents": {
                    category: len(items or [])
                    for category, items in (
                        documents or {}
                    ).items()
                },
                "inject_discrepancy": run.inject_discrepancy,
                "error": error,
            }
        )
    except Exception:
        pass


def start_match_run(run: MatchRun, storage: DocumentStorage) -> None:
    """
    Execute the match pipeline in a background thread so the
    API returns immediately and any server event loop can
    stream buffered events afterwards.
    """

    def worker() -> None:
        asyncio.run(execute_match_run(run, storage))

    threading.Thread(
        target=worker,
        name=f"match-run-{run.run_id}",
        daemon=True,
    ).start()
