import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database_operations import (
    get_match_run_events,
    get_pending_hitl_cases,
    get_recent_runs,
    get_run_detail,
    get_hitl_case as db_get_hitl_case,
    save_hitl_case as db_save_hitl_case,
    save_match_run,
    save_match_run_event,
    save_upload_session,
    update_hitl_case_decision,
    update_match_run_status,
)

logger = logging.getLogger(__name__)


class PersistenceStore:
    """
    Azure SQL-backed persistence for upload sessions, match runs,
    run events, and HITL cases.

    All methods are synchronous and use pyodbc directly.
    Failures are logged but never raise — the in-memory dicts
    remain the primary runtime store; this is a durable backup.
    """

    # ============================================================
    # UPLOAD SESSIONS
    # ============================================================

    def save_session(
        self,
        upload_id: str,
        storage_backend: str = "local",
        source_type: str = "upload",
    ) -> bool:
        return save_upload_session(
            upload_id, storage_backend, source_type
        ) or False

    # ============================================================
    # MATCH RUNS
    # ============================================================

    def save_run(
        self,
        run_id: str,
        upload_id: str,
        inject_discrepancy: bool,
        status: str = "pending",
        source_type: str = "upload",
        documents_json: str = None,
    ) -> bool:
        return save_match_run(
            run_id, upload_id, inject_discrepancy,
            status, source_type, documents_json,
        ) or False

    def update_run_status(
        self,
        run_id: str,
        status: str,
        error: str = None,
        result: dict = None,
    ) -> bool:
        result_json = json.dumps(result, default=str) if result else None
        return update_match_run_status(
            run_id, status, error, result_json,
        ) or False

    def get_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return get_recent_runs(limit) or []

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return get_run_detail(run_id)

    # ============================================================
    # MATCH RUN EVENTS
    # ============================================================

    def save_event(
        self,
        run_id: str,
        event: Dict[str, Any],
        seq: int = 0,
    ) -> bool:
        event_type = event.get("type", "unknown")
        event_data = json.dumps(event, default=str)
        return save_match_run_event(
            run_id, event_type, event_data, seq,
        ) or False

    def get_events(self, run_id: str) -> List[Dict[str, Any]]:
        raw = get_match_run_events(run_id) or []
        events = []
        for row in raw:
            try:
                parsed = json.loads(row["event_data"])
                events.append(parsed)
            except (json.JSONDecodeError, TypeError):
                events.append({"type": row["event_type"], "raw": row["event_data"]})
        return events

    # ============================================================
    # HITL CASES
    # ============================================================

    def save_hitl_case(
        self,
        case_id: str,
        run_id: str,
        status: str,
        validation_result: Any,
        evidence: List[Dict[str, Any]],
    ) -> bool:
        vr_json = json.dumps(
            validation_result, default=str
        ) if validation_result else None
        ev_json = json.dumps(evidence, default=str) if evidence else None
        return db_save_hitl_case(
            case_id, run_id, status, vr_json, ev_json,
        ) or False

    def get_hitl_case(
        self, case_id: str
    ) -> Optional[Dict[str, Any]]:
        return db_get_hitl_case(case_id)

    def update_hitl_decision(
        self,
        case_id: str,
        status: str,
        reviewer: str,
        decision_type: str,
        decision_reason: str,
        decision_comment: str,
    ) -> bool:
        return update_hitl_case_decision(
            case_id, status, reviewer, decision_type,
            decision_reason, decision_comment,
        ) or False

    def get_pending_cases(self) -> List[Dict[str, Any]]:
        return get_pending_hitl_cases() or []


persistence_store = PersistenceStore()
