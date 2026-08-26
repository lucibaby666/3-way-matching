"""
HTTP endpoints backing the monitoring dashboard pages.

    GET /api/dashboard/summary?hours=168          (ADMIN)
        Aggregated pipeline metrics from local run history,
        plus lightweight system health information.

    GET /api/dashboard/azure-metrics?hours=24     (ADMIN)
        Document Intelligence and Storage platform metrics
        queried from Azure Monitor.

    GET /api/dashboard/audit-kpis?hours=168       (ADMIN, AUDIT)
        Audit-focused HITL and exception KPIs.
"""

import asyncio
import time

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import (
    UserAccount,
    require_admin,
    require_admin_or_audit,
)
from app.env import get_env
from app.monitoring.azure_metrics import (
    get_azure_platform_metrics,
)
from app.monitoring.run_history import summarize_audit, summarize_runs

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)

MAX_HOURS = 24 * 30

_PROCESS_START = time.time()


def _system_info() -> dict:
    from app.monitoring.run_history import _get_backend

    return {
        "uptime_seconds": int(time.time() - _PROCESS_START),
        "document_storage": str(
            get_env("DOCUMENT_STORAGE", "local")
        ),
        "run_history_backend": getattr(
            _get_backend(), "name", "unknown"
        ),
        "azure_configured": bool(
            get_env("AZURE_STORAGE_CONNECTION_STRING")
            or get_env("AZURE_STORAGE_ACCOUNT_URL")
        ),
    }


@router.get("/summary")
async def dashboard_summary(
    hours: int = Query(default=168, ge=1, le=MAX_HOURS),
    user: UserAccount = Depends(require_admin),
) -> dict:
    """
    Pipeline metrics aggregated from run history.
    Admin-only.
    """

    summary = await asyncio.to_thread(
        summarize_runs, float(hours)
    )
    summary["system"] = _system_info()

    return summary


@router.get("/azure-metrics")
async def azure_metrics_summary(
    hours: int = Query(default=24, ge=1, le=MAX_HOURS),
    user: UserAccount = Depends(require_admin),
) -> dict:
    """
    Document Intelligence and Storage platform metrics
    from Azure Monitor. Returns availability flags so the
    UI can degrade gracefully when Azure is not configured.
    Admin-only.
    """

    return await asyncio.to_thread(
        get_azure_platform_metrics, int(hours)
    )


@router.get("/audit-kpis")
async def audit_kpis(
    hours: int = Query(default=168, ge=1, le=MAX_HOURS),
    user: UserAccount = Depends(require_admin_or_audit),
) -> dict:
    """
    Audit-specific KPIs: HITL workload, decision outcomes,
    reviewer activity and SLA breaches. Available to the
    AUDIT role (and ADMIN).
    """

    return await asyncio.to_thread(
        summarize_audit, float(hours)
    )
