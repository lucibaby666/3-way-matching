from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.pipeline import EVIDENCE_ROOT
from app.api.routes import router
from app.auth.routes import router as auth_router
from app.monitoring.dashboard_routes import (
    router as dashboard_router,
)
from app.monitoring.json_logging import (
    configure_structured_logging,
)


configure_structured_logging()

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


@app.on_event("startup")
async def startup_event():
    # Ensure local folders exist
    Path("logs").mkdir(parents=True, exist_ok=True)
    Path("outputs").mkdir(parents=True, exist_ok=True)
    try:
        from database_operations import create_audit_tables, verify_database_connection
        connected, msg = verify_database_connection()
        if connected:
            create_audit_tables()
    except Exception:
        pass




app.include_router(auth_router)
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
