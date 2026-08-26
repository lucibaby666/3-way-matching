"""
HTTP endpoints backing the monitoring dashboard page.

    GET /api/dashboard/summary?hours=168
        Aggregated pipeline metrics from local run history.

    GET /api/dashboard/azure-metrics?hours=24
        Document Intelligence and Storage platform metrics
        queried from Azure Monitor.
"""

import asyncio

from fastapi import APIRouter, Query

from app.monitoring.azure_metrics import (
    get_azure_platform_metrics,
)
from app.monitoring.run_history import summarize_runs

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
)

MAX_HOURS = 24 * 30


@router.get("/summary")
async def dashboard_summary(
    hours: int = Query(default=168, ge=1, le=MAX_HOURS),
) -> dict:
    """
    Pipeline metrics aggregated from run history.
    """

    return await asyncio.to_thread(
        summarize_runs, float(hours)
    )


@router.get("/azure-metrics")
async def azure_metrics_summary(
    hours: int = Query(default=24, ge=1, le=MAX_HOURS),
) -> dict:
    """
    Document Intelligence and Storage platform metrics
    from Azure Monitor. Returns availability flags so the
    UI can degrade gracefully when Azure is not configured.
    """

    return await asyncio.to_thread(
        get_azure_platform_metrics, int(hours)
    )
