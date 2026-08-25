"""
Run history persistence and aggregation for the
monitoring dashboard.

Each pipeline run appends one JSON line to a local
JSONL file. HITL decisions append one JSON line each.
The dashboard endpoints aggregate these records.

Record shapes:

    Run:
        {
            "record_type": "run",
            "run_id": "...",
            "upload_id": "...",
            "timestamp": "<finished at, ISO 8601 UTC>",
            "outcome": "completed" | "failed",
            "status": "PASS" | "EXCEPTION" | null,
            "exception_count": int,
            "exception_types": {"PRICE_MISMATCH": 2},
            "hitl_created": bool,
            "case_id": str | null,
            "durations_ms": {"intake": ..., "matching": ...},
            "documents": {"contracts": n, ...},
            "inject_discrepancy": bool,
            "error": str | null,
        }

    Decision:
        {
            "record_type": "decision",
            "case_id": "...",
            "timestamp": "<ISO 8601 UTC>",
            "decision": "APPROVE",
            "reviewer": "...",
        }
"""

import json
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HISTORY_PATH = Path("outputs/run_history.jsonl")

_lock = threading.Lock()


def record_event(record: Dict[str, Any]) -> None:
    """
    Append one monitoring record as a single JSON line.
    Thread-safe; never raises into the caller's flow.
    """

    try:
        line = json.dumps(record, default=str)

        with _lock:
            HISTORY_PATH.parent.mkdir(
                parents=True, exist_ok=True
            )

            with HISTORY_PATH.open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write(line + "\n")
    except OSError:
        pass


def read_events(
    limit_hours: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Read monitoring records, optionally limited to the
    most recent N hours. Malformed lines are skipped.
    """

    if not HISTORY_PATH.exists():
        return []

    cutoff = None

    if limit_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=limit_hours
        )

    events: List[Dict[str, Any]] = []

    with HISTORY_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()

            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if cutoff is not None:
                timestamp = event.get("timestamp")

                if not timestamp:
                    continue

                try:
                    parsed = _parse_timestamp(timestamp)
                except ValueError:
                    continue

                if parsed < cutoff:
                    continue

            events.append(event)

    return events


def summarize_runs(
    limit_hours: float = 168,
) -> Dict[str, Any]:
    """
    Aggregate run and decision records for the dashboard.
    """

    events = read_events(limit_hours)

    runs = [
        event
        for event in events
        if event.get("record_type") == "run"
    ]
    decisions = [
        event
        for event in events
        if event.get("record_type") == "decision"
    ]

    completed_runs = [
        run
        for run in runs
        if run.get("outcome") == "completed"
    ]
    failed_runs = [
        run
        for run in runs
        if run.get("outcome") != "completed"
    ]
    passed_runs = [
        run
        for run in completed_runs
        if run.get("status") == "PASS"
    ]

    exception_counter: Counter = Counter()
    total_exceptions = 0

    for run in completed_runs:
        types = run.get("exception_types") or {}

        for exception_type, count in types.items():
            exception_counter[exception_type] += count
            total_exceptions += count

    durations = [
        run.get("durations_ms", {}).get("total")
        for run in completed_runs
    ]

    durations = [
        value
        for value in durations
        if isinstance(value, (int, float))
    ]

    avg_duration_ms = (
        sum(durations) / len(durations)
        if durations
        else None
    )

    duration_breakdown = _avg_duration_breakdown(
        completed_runs
    )
    runs_per_day = _runs_per_day(completed_runs)

    documents_processed = sum(
        sum((run.get("documents") or {}).values())
        for run in completed_runs
    )

    hitl_created_cases = {
        run["case_id"]
        for run in completed_runs
        if run.get("hitl_created") and run.get("case_id")
    }
    reviewed_case_ids = {
        decision.get("case_id")
        for decision in decisions
        if decision.get("case_id")
    }

    open_hitl_cases = len(
        hitl_created_cases - reviewed_case_ids
    )

    recent_runs = sorted(
        runs,
        key=lambda run: run.get("timestamp") or "",
        reverse=True,
    )[:10]

    return {
        "window_hours": limit_hours,
        "totals": {
            "runs": len(runs),
            "completed": len(completed_runs),
            "failed": len(failed_runs),
            "passed": len(passed_runs),
            "with_exceptions": len(completed_runs)
            - len(passed_runs),
            "exceptions_found": total_exceptions,
            "documents_processed": documents_processed,
            "hitl_cases_created": len(hitl_created_cases),
            "open_hitl_cases": open_hitl_cases,
        },
        "match_rate_pct": round(
            100 * len(passed_runs) / len(completed_runs), 1
        )
        if completed_runs
        else None,
        "avg_duration_ms": avg_duration_ms,
        "duration_breakdown_avg_ms": duration_breakdown,
        "exception_breakdown": dict(exception_counter),
        "runs_per_day": runs_per_day,
        "recent_runs": recent_runs,
    }


# ============================================================
# INTERNAL HELPERS
# ============================================================


def _parse_timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def _avg_duration_breakdown(
    runs: List[Dict[str, Any]],
) -> Dict[str, float]:
    sums: Counter = Counter()
    counts: Counter = Counter()

    for run in runs:
        durations = run.get("durations_ms") or {}

        for phase, value in durations.items():
            if phase == "total":
                continue

            if isinstance(value, (int, float)):
                sums[phase] += value
                counts[phase] += 1

    return {
        phase: round(sums[phase] / counts[phase], 1)
        for phase in sums
        if counts[phase]
    }


def _runs_per_day(
    runs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, int]] = {}

    for run in runs:
        timestamp = run.get("timestamp")

        if not timestamp:
            continue

        try:
            day = _parse_timestamp(timestamp).date().isoformat()
        except ValueError:
            continue

        bucket = buckets.setdefault(
            day, {"total": 0, "pass": 0, "exception": 0}
        )
        bucket["total"] += 1

        if run.get("status") == "PASS":
            bucket["pass"] += 1
        else:
            bucket["exception"] += 1

    return [
        {"date": day, **values}
        for day, values in sorted(buckets.items())
    ]
