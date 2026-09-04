from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class HITLDecisionType(str, Enum):
    """
    Decisions that a human reviewer can make
    on a HITL case.
    """

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    OVERRIDE = "OVERRIDE"


@dataclass
class HITLDecision:
    """
    Represents a human decision made on a HITL case.

    The decision is explicitly made by a human reviewer.
    The MAF agent must never create this decision
    automatically.
    """

    decision: HITLDecisionType
    reviewer: str
    comment: Optional[str]
    timestamp: datetime
    reason: Optional[str] = None