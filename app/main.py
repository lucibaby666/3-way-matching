from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.pipeline import EVIDENCE_ROOT
from app.api.routes import router
from app.monitoring.dashboard_routes import (
    router as dashboard_router,
)


app = FastAPI(
    title="Agentic 3-Way Matching POC",
    description="Agentic automation for Contract, Purchase Order, and Invoice 3-way matching.",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "agentic-3way-matching",
        "version": "0.1.0",
    }


app.include_router(router)
app.include_router(dashboard_router)

EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
app.mount(
    "/evidence",
    StaticFiles(directory=EVIDENCE_ROOT),
    name="evidence",
)

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "Frontend" / "frontend"

if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
