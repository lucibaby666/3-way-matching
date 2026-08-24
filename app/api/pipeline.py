import asyncio
import threading
from pathlib import Path
from typing import Any, Dict, List

from app.api.runtime import MatchRun
from app.capabilities.document_set_loader import (
    DocumentSetLoader,
)
from app.capabilities.evidence_generator import (
    EvidenceGenerator,
)
from app.matching.matching_engine import MatchingEngine
from app.storage.document_storage import DocumentStorage

EVIDENCE_ROOT = Path("outputs/evidence")

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
        run.emit(
            {
                "type": "step",
                "step": step_name,
                "message": message,
            }
        )

    try:
        run.status = "running"

        # --------------------------------------------------
        # 1. INTAKE
        # --------------------------------------------------

        step("intake", "Loading uploaded documents.")

        loader = DocumentSetLoader(storage=storage)
        loaded = await asyncio.to_thread(loader.load)

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
            output_dir=str(evidence_dir)
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

    except Exception as error:
        run.emit(
            {
                "type": "error",
                "message": str(error) or error.__class__.__name__,
            }
        )


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
