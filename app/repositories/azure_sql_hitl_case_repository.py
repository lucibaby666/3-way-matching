import json
from datetime import datetime, timezone
from typing import List, Optional

from app.models.hitl_case import HITLCase, HITLCaseStatus
from app.models.hitl_decision import HITLDecision, HITLDecisionType
from app.models.validation_result import ValidationResult, ValidationException
from app.repositories.hitl_case_repository import (
    HITLCaseRepository,
)
from app.persistence.store import persistence_store


class AzureSqlHITLCaseRepository(HITLCaseRepository):
    """
    Azure SQL-backed HITL case repository.

    Cases are persisted to the hitl_cases table so they
    survive server restarts. The in-memory dict is kept
    as a fast cache; writes go to both.
    """

    def __init__(self):
        self._cases = {}

    def save(self, hitl_case: HITLCase) -> HITLCase:
        if hitl_case is None:
            raise ValueError("HITL case cannot be None.")
        if hitl_case.case_id in self._cases:
            raise ValueError(
                f"HITL case already exists: {hitl_case.case_id}"
            )

        self._cases[hitl_case.case_id] = hitl_case

        vr = _serialize_validation_result(
            hitl_case.validation_result
        )
        persistence_store.save_hitl_case(
            case_id=hitl_case.case_id,
            run_id=getattr(hitl_case, "run_id", None) or "",
            status=hitl_case.status.value,
            validation_result=vr,
            evidence=hitl_case.evidence,
        )

        return hitl_case

    def get(self, case_id: str) -> Optional[HITLCase]:
        if not case_id:
            raise ValueError("case_id cannot be empty.")

        if case_id in self._cases:
            return self._cases[case_id]

        row = persistence_store.get_hitl_case(case_id)
        if row is None:
            return None

        hitl_case = _row_to_hitl_case(row)
        self._cases[case_id] = hitl_case
        return hitl_case

    def update(self, hitl_case: HITLCase) -> HITLCase:
        if hitl_case is None:
            raise ValueError("HITL case cannot be None.")
        if hitl_case.case_id not in self._cases:
            raise ValueError(
                f"HITL case does not exist: {hitl_case.case_id}"
            )

        self._cases[hitl_case.case_id] = hitl_case

        if hitl_case.decision is not None:
            persistence_store.update_hitl_decision(
                case_id=hitl_case.case_id,
                status=hitl_case.status.value,
                reviewer=hitl_case.reviewer or "",
                decision_type=hitl_case.decision.decision.value,
                decision_reason=getattr(
                    hitl_case.decision, "reason", ""
                ) or "",
                decision_comment=hitl_case.decision.comment or "",
            )

        return hitl_case


def _serialize_validation_result(
    vr: ValidationResult,
) -> dict:
    if vr is None:
        return {}
    return {
        "status": vr.status,
        "exceptions": [
            {
                "type": e.type,
                "item_code": e.item_code,
                "field": e.field,
                "expected": str(e.expected) if e.expected is not None else None,
                "actual": str(e.actual) if e.actual is not None else None,
                "tolerance": e.tolerance,
            }
            for e in (vr.exceptions or [])
        ],
    }


def _row_to_hitl_case(row: dict) -> HITLCase:
    status = HITLCaseStatus(row["status"])

    vr = None
    if row.get("validation_result"):
        try:
            data = json.loads(row["validation_result"])
            exceptions = [
                ValidationException(**exc)
                for exc in data.get("exceptions", [])
            ]
            vr = ValidationResult(
                status=data.get("status", "EXCEPTION"),
                exceptions=exceptions,
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            vr = ValidationResult(status="EXCEPTION", exceptions=[])

    decision = None
    if row.get("decision_type"):
        decision = HITLDecision(
            decision=HITLDecisionType(row["decision_type"]),
            reviewer=row.get("reviewer", ""),
            comment=row.get("decision_comment", ""),
            timestamp=row.get("decision_timestamp") or datetime.now(timezone.utc),
        )
        if hasattr(decision, "reason") is False:
            decision.reason = row.get("decision_reason", "")

    evidence = []
    if row.get("evidence"):
        try:
            evidence = json.loads(row["evidence"])
        except (json.JSONDecodeError, TypeError):
            evidence = []

    hitl_case = HITLCase(
        case_id=row["case_id"],
        status=status,
        validation_result=vr or ValidationResult(status="EXCEPTION"),
        created_at=row.get("created_at") or datetime.now(timezone.utc),
        reviewer=row.get("reviewer"),
        evidence=evidence,
        decision=decision,
    )
    hitl_case.run_id = row.get("run_id", "")
    return hitl_case
