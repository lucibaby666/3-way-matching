from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.capabilities.hitl_case_service import HITLCaseService
from app.capabilities.hitl_decision import HITLDecisionCapability
from app.capabilities.hitl_routing import HITLRoutingCapability
from app.repositories.in_memory_hitl_case_repository import (
    InMemoryHITLCaseRepository,
)
from app.storage.in_memory_document_storage import (
    InMemoryDocumentStorage,
)


def create_hitl_service() -> HITLCaseService:
    return HITLCaseService(
        repository=InMemoryHITLCaseRepository(),
        routing_capability=HITLRoutingCapability(),
        decision_capability=HITLDecisionCapability(),
    )


hitl_service = create_hitl_service()


@dataclass
class UploadSession:
    upload_id: str
    storage: InMemoryDocumentStorage
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class MatchRun:
    run_id: str
    upload_id: str
    inject_discrepancy: bool
    status: str = "pending"
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = field(default_factory=list)

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


upload_sessions: Dict[str, UploadSession] = {}
match_runs: Dict[str, MatchRun] = {}
