"""
Log Service for Aggregated Audit & System Log Dashboard.
Queries SQL Server audit tables and parses local file-based logs.
"""

import csv
import io
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ThreeWayMatching")


def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse standard Python log line: YYYY-MM-DD HH:MM:SS - Name - LEVEL - Message"""
    pattern = r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*-\s*([^-]+)\s*-\s*([A-Z]+)\s*-\s*(.*)$"
    match = re.match(pattern, line.strip())
    if match:
        ts_str, logger_name, level, message = match.groups()
        return {
            "audit_id": f"LOG-{ts_str.replace(' ', '_').replace(':', '')[:15]}",
            "event_type": "APPLICATION_LOG",
            "severity": level.strip(),
            "user": "system",
            "action": message.strip(),
            "resource": logger_name.strip(),
            "resource_type": "LOGGER",
            "status": "FAILED" if level in {"ERROR", "CRITICAL"} else "SUCCESS",
            "error": message.strip() if level in {"ERROR", "CRITICAL"} else None,
            "metadata": {},
            "inserted_at": ts_str,
            "source": "file",
        }
    return None


def get_file_logs(limit: int = 200, severity: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reads and parses recent lines from logs/ directory and outputs/run_history.jsonl"""
    results: List[Dict[str, Any]] = []
    logs_dir = Path("logs")

    # 1. Read JSONL run history records if available
    history_file = Path("outputs/run_history.jsonl")
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines[-limit:]):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        rec_type = record.get("record_type", "run")
                        if rec_type == "run":
                            status = record.get("status") or record.get("outcome", "completed")
                            sev = "WARNING" if status == "EXCEPTION" else ("ERROR" if status == "failed" else "INFO")
                            results.append({
                                "audit_id": f"RUN-{record.get('run_id', '')[:8]}",
                                "event_type": "MATCH_RUN",
                                "severity": sev,
                                "user": "system",
                                "action": f"Matching run {record.get('run_id', '')[:8]} finished with {status} ({record.get('exception_count', 0)} exceptions)",
                                "resource": record.get("run_id", ""),
                                "resource_type": "RUN",
                                "status": status,
                                "error": record.get("error"),
                                "metadata": record,
                                "inserted_at": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
                                "source": "file_jsonl",
                            })
                        elif rec_type == "decision":
                            dec = record.get("decision", "REVIEWED")
                            results.append({
                                "audit_id": f"DEC-{record.get('case_id', '')[:8]}",
                                "event_type": "HITL_DECISION",
                                "severity": "AUDIT",
                                "user": record.get("reviewer", "human"),
                                "action": f"Decision {dec} applied on case {record.get('case_id', '')}",
                                "resource": record.get("case_id", ""),
                                "resource_type": "CASE",
                                "status": dec,
                                "error": None,
                                "metadata": record,
                                "inserted_at": record.get("timestamp", datetime.now(timezone.utc).isoformat()),
                                "source": "file_jsonl",
                            })
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Could not read run_history.jsonl: {e}")

    # 2. Read text log files
    if logs_dir.exists():
        for log_file in sorted(logs_dir.glob("*.log"), reverse=True):
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    for line in reversed(lines[-limit:]):
                        parsed = parse_log_line(line)
                        if parsed:
                            results.append(parsed)
                        if len(results) >= limit * 2:
                            break
            except Exception as e:
                logger.debug(f"Could not read log file {log_file}: {e}")

    # Apply filters
    filtered = []
    sev_filter = severity.upper() if severity and severity.upper() != "ALL" else None
    search_term = search.lower() if search else None

    for entry in results:
        if sev_filter and entry.get("severity", "").upper() != sev_filter:
            continue
        if search_term:
            match_str = f"{entry.get('action', '')} {entry.get('audit_id', '')} {entry.get('user', '')} {entry.get('resource', '')} {entry.get('error', '')}".lower()
            if search_term not in match_str:
                continue
        filtered.append(entry)

    # Sort descending by timestamp
    filtered.sort(key=lambda x: str(x.get("inserted_at", "")), reverse=True)
    return filtered[:limit]


def get_aggregated_logs(
    limit: int = 200,
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    search: Optional[str] = None,
    source: str = "all",
) -> List[Dict[str, Any]]:
    """Retrieve logs from Database, Files, or Both combined"""
    db_logs: List[Dict[str, Any]] = []
    file_logs: List[Dict[str, Any]] = []

    if source in {"all", "db"}:
        try:
            from database_operations import get_recent_audit_logs
            db_logs = get_recent_audit_logs(
                limit=limit,
                severity=severity,
                event_type=event_type,
                search=search,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch db audit logs: {e}")

    if source in {"all", "file"} or (source == "db" and not db_logs):
        file_logs = get_file_logs(limit=limit, severity=severity, search=search)

    combined = db_logs + file_logs
    # Deduplicate by audit_id if any overlap
    seen = set()
    unique_logs = []
    for log in combined:
        aid = log.get("audit_id")
        if aid and aid in seen:
            continue
        if aid:
            seen.add(aid)
        unique_logs.append(log)

    unique_logs.sort(key=lambda x: str(x.get("inserted_at", "")), reverse=True)
    return unique_logs[:limit]


def get_log_dashboard_stats() -> Dict[str, Any]:
    """Generates KPI metrics, severity breakdowns, timeline buckets, and health statistics"""
    logs = get_aggregated_logs(limit=1000)

    severity_counts: Dict[str, int] = {
        "INFO": 0,
        "WARNING": 0,
        "ERROR": 0,
        "CRITICAL": 0,
        "AUDIT": 0,
    }
    event_type_counts: Dict[str, int] = {}
    timeline_map: Dict[str, int] = {}
    user_counts: Dict[str, int] = {}
    recent_errors: List[Dict[str, Any]] = []

    for log in logs:
        # Severity count
        sev = str(log.get("severity", "INFO")).upper()
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Event type count
        ev_type = str(log.get("event_type", "SYSTEM")).upper()
        event_type_counts[ev_type] = event_type_counts.get(ev_type, 0) + 1

        # User count
        u = str(log.get("user", "system"))
        user_counts[u] = user_counts.get(u, 0) + 1

        # Timeline bucket (by YYYY-MM-DD HH:00)
        ts_str = str(log.get("inserted_at", ""))
        bucket = ts_str[:13] if len(ts_str) >= 13 else "Recent"
        timeline_map[bucket] = timeline_map.get(bucket, 0) + 1

        # Error collection
        if sev in {"ERROR", "CRITICAL"} or log.get("status") == "FAILED" or log.get("error"):
            if len(recent_errors) < 10:
                recent_errors.append(log)

    # Database connection status
    db_connected = False
    db_count = 0
    try:
        from database_operations import verify_database_connection, get_audit_count
        db_connected, _ = verify_database_connection()
        if db_connected:
            db_count = get_audit_count()
    except Exception:
        pass

    # ChromaDB vectors
    chroma_vectors = 0
    try:
        from app.capabilities.smart_approval import get_smart_approval_system
        chroma_vectors = get_smart_approval_system().get_stats().get("chromadb_vectors", 0)
    except Exception:
        pass

    # User activity and decision breakdown
    user_decision_stats = []
    try:
        from app.auth.users import list_users
        from app.monitoring.run_history import summarize_audit
        audit_summary = summarize_audit(limit_hours=168*4)
        reviewer_breakdown = audit_summary.get("reviewer_breakdown", {})
        registered_users = list_users()

        all_usernames = set([u["username"] for u in registered_users] + list(user_counts.keys()) + list(reviewer_breakdown.keys()))
        for uname in sorted(all_usernames):
            if uname in {"system", "unknown", ""}:
                continue
            role = "AUDIT"
            for ru in registered_users:
                if ru["username"] == uname:
                    role = ru.get("role", "AUDIT")
                    break

            r_stats = reviewer_breakdown.get(uname, {})
            tot_dec = r_stats.get("total", 0)
            app = r_stats.get("APPROVE", 0)
            rej = r_stats.get("REJECT", 0)
            ovr = r_stats.get("OVERRIDE", 0)
            rate = f"{round((app / max(tot_dec, 1)) * 100)}%" if tot_dec > 0 else "—"

            user_decision_stats.append({
                "username": uname,
                "role": role,
                "total_logs": user_counts.get(uname, 0),
                "total_decisions": tot_dec,
                "approved": app,
                "rejected": rej,
                "override": ovr,
                "approval_rate": rate,
                "status": "Active",
            })
    except Exception as e:
        logger.warning(f"Could not aggregate user decision stats: {e}")

    # Source breakdown
    source_counts = {"database": 0, "file": 0}
    error_timeline_map = {}
    for log in logs:
        src = "database" if log.get("source") == "database" else "file"
        source_counts[src] += 1
        ts_str = str(log.get("inserted_at", ""))
        bucket = ts_str[:13] if len(ts_str) >= 13 else "Recent"
        if bucket not in error_timeline_map:
            error_timeline_map[bucket] = {"errors": 0, "warnings": 0, "total": 0}
        error_timeline_map[bucket]["total"] += 1
        sev = str(log.get("severity", "INFO")).upper()
        if sev in {"ERROR", "CRITICAL"}:
            error_timeline_map[bucket]["errors"] += 1
        elif sev in {"WARNING", "WARN"}:
            error_timeline_map[bucket]["warnings"] += 1

    sorted_err_tl = sorted(error_timeline_map.items())[-24:]
    error_tl_labels = [item[0] for item in sorted_err_tl]
    error_tl_errors = [item[1]["errors"] for item in sorted_err_tl]
    error_tl_warnings = [item[1]["warnings"] for item in sorted_err_tl]
    error_tl_totals = [item[1]["total"] for item in sorted_err_tl]

    # Sorted timeline for Chart.js
    sorted_timeline = sorted(timeline_map.items())
    timeline_labels = [item[0] for item in sorted_timeline[-24:]]
    timeline_data = [item[1] for item in sorted_timeline[-24:]]

    total_logs = len(logs)
    error_total = severity_counts.get("ERROR", 0) + severity_counts.get("CRITICAL", 0)
    error_rate = round((error_total / max(total_logs, 1)) * 100, 1)

    return {
        "kpis": {
            "total_logs": total_logs,
            "database_audit_logs": db_count,
            "error_count": error_total,
            "warning_count": severity_counts.get("WARNING", 0),
            "audit_decisions": severity_counts.get("AUDIT", 0),
            "chroma_vectors": chroma_vectors,
            "error_rate_pct": error_rate,
            "database_connected": db_connected,
        },
        "severity_breakdown": severity_counts,
        "events_by_type": event_type_counts,
        "sources_breakdown": source_counts,
        "timeline": {
            "labels": timeline_labels,
            "data": timeline_data,
        },
        "error_timeline": {
            "labels": error_tl_labels,
            "errors": error_tl_errors,
            "warnings": error_tl_warnings,
            "totals": error_tl_totals,
        },
        "top_users": user_counts,
        "user_decision_stats": user_decision_stats,
        "recent_errors": recent_errors,
    }


def export_logs_as_csv(logs: List[Dict[str, Any]]) -> str:
    """Exports logs as a CSV string"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Audit ID", "Timestamp", "Severity", "Event Type", "User", "Action", "Resource", "Status", "Error", "Source"
    ])
    for log in logs:
        writer.writerow([
            log.get("audit_id", ""),
            log.get("inserted_at", ""),
            log.get("severity", ""),
            log.get("event_type", ""),
            log.get("user", ""),
            log.get("action", ""),
            log.get("resource", ""),
            log.get("status", ""),
            log.get("error", ""),
            log.get("source", ""),
        ])
    return output.getvalue()
