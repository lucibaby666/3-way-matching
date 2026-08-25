import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.api.runtime import MatchRun
from app.capabilities.document_set_loader import (
    DocumentSetLoader,
)
from app.capabilities.document_snip import DocumentSnip
from app.capabilities.evidence_generator import (
    EvidenceGenerator,
)
from app.matching.matching_engine import MatchingEngine
from app.monitoring.json_logging import log_event
from app.monitoring.run_history import record_event
from app.storage.document_storage import DocumentStorage

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


def _exception_as_dict(exception: Any) -> Dict[str, Any]:
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

    return data


async def execute_match_run(
    run: MatchRun,
    storage: DocumentStorage,
) -> None:
    """
    Run the full 3-way matching pipeline for one uploaded
    document set and stream progress into the run.
    """

    def step(step_name: str, message: str) -> None:
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

        # --------------------------------------------------
        # 1. INTAKE
        # --------------------------------------------------

        step("intake", "Loading uploaded documents.")

        loader = DocumentSetLoader(storage=storage)
        loaded = await asyncio.to_thread(loader.load)
        mark_phase("intake")

        documents = loaded["documents"]
        contracts = loaded["contracts"]
        purchase_orders = loaded["purchase_orders"]
        invoices = loaded["invoices"]

        step(
            "intake",
            f"Loaded {len(contracts)} contract(s), "
            f"{len(purchase_orders)} PO(s), "
            f"{len(invoices)} invoice(s).",
        )

        # --------------------------------------------------
        # 2. DISCREPANCY INJECTION (DEMO ONLY)
        # --------------------------------------------------

        if run.inject_discrepancy:
            invoice = invoices[0]

            if not invoice.line_items:
                raise RuntimeError(
                    "Invoice contains no line items."
                )

            original_quantity = invoice.line_items[0].quantity
            original_price = invoice.line_items[0].unit_price

            invoice.line_items[0].quantity = 110
            invoice.line_items[0].unit_price = 260

            step(
                "demo-discrepancy",
                f"Invoice {invoice.line_items[0].item_code} "
                f"modified in memory (qty {original_quantity} -> 110, "
                f"price {original_price} -> 260).",
            )

        # --------------------------------------------------
        # 3. DETERMINISTIC MATCHING + EVIDENCE
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
            f"Deterministic status: {result.status}.",
        )

        # --------------------------------------------------
        # 4. HITL ROUTING
        # --------------------------------------------------

        from app.api.runtime import hitl_service

        hitl_case = await asyncio.to_thread(
            hitl_service.create_case,
            result,
        )
        mark_phase("hitl_routing")

        if hitl_case is None:
            step(
                "hitl",
                "No exceptions routed to human review.",
            )
        else:
            step(
                "hitl",
                f"Case {hitl_case.case_id} created for review.",
            )

        # --------------------------------------------------
        # 5. BUILD RESULT PAYLOAD
        # --------------------------------------------------

        first = lambda category: (
            loaded["documents"][category][0]
            if loaded["documents"].get(category)
            else {}
        )  # noqa: E731

        payload: Dict[str, Any] = {
            "status": result.status,
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
            "exceptions": [
                _exception_as_dict(exception)
                for exception in result.exceptions
            ],
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
            "Pipeline finished.",
        )

        run.result = payload
        run.emit({"type": "done", "payload": payload})
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

        log_event(
            logger,
            "run_completed",
            run_id=run.run_id,
            upload_id=run.upload_id,
            status=result.status,
            exception_count=len(result.exceptions),
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
        run.emit(
            {
                "type": "error",
                "message": str(error) or error.__class__.__name__,
            }
        )
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
