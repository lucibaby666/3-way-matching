import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.capabilities.hitl_case_service import HITLCaseService
from app.capabilities.hitl_decision import HITLDecisionCapability
from app.capabilities.hitl_routing import HITLRoutingCapability
from app.persistence.store import persistence_store
from app.repositories.azure_sql_hitl_case_repository import (
    AzureSqlHITLCaseRepository,
)
from app.storage.document_storage import DocumentStorage


def create_hitl_service() -> HITLCaseService:
    return HITLCaseService(
        repository=AzureSqlHITLCaseRepository(),
        routing_capability=HITLRoutingCapability(),
        decision_capability=HITLDecisionCapability(),
    )


hitl_service = create_hitl_service()


@dataclass
class UploadSession:
    upload_id: str
    storage: DocumentStorage
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    filenames: Optional[Dict[str, List[str]]] = None


@dataclass
class MatchRun:
    run_id: str
    upload_id: str
    inject_discrepancy: bool
    status: str = "pending"
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    source_type: str = "upload"
    documents_snapshot: Optional[Dict[str, Any]] = None

    @property
    def finished(self) -> bool:
        return self.status in {"completed", "failed"}

    def emit(self, event: Dict[str, Any]) -> None:
        self.events.append(event)

        if event["type"] == "done":
            self.status = "completed"
        elif event["type"] == "error":
            self.status = "failed"
            self.error = event.get("message")

        seq = len(self.events)
        try:
            persistence_store.save_event(
                self.run_id, event, seq=seq
            )
        except Exception:
            pass


upload_sessions: Dict[str, UploadSession] = {}
match_runs: Dict[str, MatchRun] = {}


def persist_session(session: UploadSession) -> None:
    upload_sessions[session.upload_id] = session
    try:
        persistence_store.save_session(
            session.upload_id,
            storage_backend="azure"
            if hasattr(session.storage, "container_name")
            else "local",
            source_type="upload",
        )
    except Exception:
        pass


def persist_run(run: MatchRun) -> None:
    match_runs[run.run_id] = run
    try:
        docs_json = json.dumps(
            run.documents_snapshot, default=str
        ) if run.documents_snapshot else None
        persistence_store.save_run(
            run_id=run.run_id,
            upload_id=run.upload_id,
            inject_discrepancy=run.inject_discrepancy,
            status=run.status,
            source_type=run.source_type,
            documents_json=docs_json,
        )
    except Exception:
        pass
