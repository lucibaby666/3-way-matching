"""
Azure platform metrics for the monitoring dashboard.

Queries Azure Monitor platform metrics for the Document
Intelligence account and the Storage account using the
azure-mgmt-monitor SDK (ARM metrics API).

Configuration (all optional; when missing, that resource
is reported as not configured):

    azure-di-resource-id
        Full resource ID of the Document Intelligence
        (Cognitive Services) account, e.g.
        /subscriptions/<sub>/resourceGroups/<rg>/providers/
        Microsoft.CognitiveServices/accounts/<name>

    azure-storage-resource-id
        Full resource ID of the storage account, e.g.
        /subscriptions/<sub>/resourceGroups/<rg>/providers/
        Microsoft.Storage/storageAccounts/<name>
        (the blob service sub-resource is queried)

Authentication uses DefaultAzureCredential (same as the
existing blob storage backend). The caller needs the
Monitoring Reader role on each resource.

Metric names differ between resources and API versions, so
unsupported names are dropped and failures are skipped.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.env import get_env

DI_METRIC_CANDIDATES = [
    "ProcessedPages",
    "TotalCalls",
    "SuccessfulCalls",
    "ClientErrors",
    "ServerErrors",
    "Latency",
]

STORAGE_BLOB_METRICS = [
    "Transactions",
    "Ingress",
    "Egress",
    "SuccessE2ELatency",
    "SuccessServerLatency",
    "Availability",
]


def get_azure_platform_metrics(
    window_hours: int = 24,
) -> Dict[str, Any]:
    """
    Query Azure Monitor for Document Intelligence and
    Storage blob metrics over the requested window.

    Returns a payload where each section carries either
    metrics or an explanation of why none are available.
    """

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=window_hours)
    timespan = (
        start.strftime("%Y-%m-%dT%H:%M:%SZ")
        + "/"
        + end.strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    return {
        "window_hours": window_hours,
        "document_intelligence": _query_resource(
            resource_id=get_env("AZURE_DI_RESOURCE_ID"),
            metric_candidates=DI_METRIC_CANDIDATES,
            namespace="Microsoft.CognitiveServices/accounts",
            timespan=timespan,
            configured_hint="Set azure-di-resource-id.",
        ),
        "storage": _query_resource(
            resource_id=_blob_service_id(
                get_env("AZURE_STORAGE_RESOURCE_ID")
            ),
            metric_candidates=STORAGE_BLOB_METRICS,
            namespace=(
                "Microsoft.Storage/storageAccounts"
                "/blobServices"
            ),
            timespan=timespan,
            configured_hint=(
                "Set azure-storage-resource-id."
            ),
        ),
    }


# ============================================================
# INTERNAL HELPERS
# ============================================================


def _blob_service_id(resource_id: str | None) -> str | None:
    if not resource_id:
        return None

    if resource_id.rstrip("/").endswith("blobServices/default"):
        return resource_id

    return resource_id.rstrip("/") + "/blobServices/default"


def _subscription_id_from(resource_id: str) -> str | None:
    match = re.search(
        r"/subscriptions/([^/]+)", resource_id
    )
    return match.group(1) if match else None


def _query_resource(
    resource_id: str | None,
    metric_candidates: List[str],
    namespace: str,
    timespan: str,
    configured_hint: str,
) -> Dict[str, Any]:
    if not resource_id:
        return {
            "available": False,
            "reason": f"Not configured. {configured_hint}",
            "metrics": [],
        }

    subscription_id = _subscription_id_from(resource_id)

    if not subscription_id:
        return {
            "available": False,
            "reason": (
                "Invalid resource ID. Expected a full ID "
                "starting with /subscriptions/."
            ),
            "metrics": [],
        }

    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.monitor import (
            MonitorManagementClient,
        )
    except ImportError:
        return {
            "available": False,
            "reason": (
                "azure-mgmt-monitor is not installed."
            ),
            "metrics": [],
        }

    try:
        client = MonitorManagementClient(
            credential=DefaultAzureCredential(),
            subscription_id=subscription_id,
        )

        response = client.metrics.list(
            resource_uri=resource_id,
            timespan=timespan,
            interval="PT1H",
            metricnames=",".join(metric_candidates),
            metricnamespace=namespace,
            aggregation="Total,Average",
        )
    except Exception as error:
        return {
            "available": False,
            "reason": str(error)
            or error.__class__.__name__,
            "metrics": [],
        }

    metrics: List[Dict[str, Any]] = []

    for metric in response.value:
        name = getattr(getattr(metric, "name", None), "value", None)

        points: List[Dict[str, Any]] = []
        total = 0.0
        has_total = False
        average_sum = 0.0
        average_count = 0

        for series in metric.timeseries:
            for value in series.data:
                timestamp = getattr(value, "time_stamp", None)

                point: Dict[str, Any] = {
                    "timestamp": timestamp.isoformat()
                    if timestamp
                    else None,
                }

                total_value = getattr(value, "total", None)

                if total_value is not None:
                    point["total"] = total_value
                    total += total_value
                    has_total = True

                average_value = getattr(
                    value, "average", None
                )

                if average_value is not None:
                    point["average"] = average_value
                    average_sum += average_value
                    average_count += 1

                if (
                    total_value is None
                    and average_value is None
                ):
                    continue

                points.append(point)

        entry: Dict[str, Any] = {
            "name": name,
            "display_name": name,
            "unit": str(getattr(metric, "unit", ""))
            or None,
            "points": points,
        }

        if has_total:
            entry["sum"] = round(total, 2)

        if average_count:
            entry["avg"] = round(
                average_sum / average_count, 2
            )

        metrics.append(entry)

    metrics.sort(key=lambda item: item["display_name"])

    return {
        "available": bool(metrics),
        "reason": None
        if metrics
        else "No metrics returned for this resource.",
        "metrics": metrics,
    }
