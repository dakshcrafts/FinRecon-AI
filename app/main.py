import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.routers import (
    auth,
    dashboard,
    invoices,
    payments,
    reconciliation,
    reports,
    settings as settings_router,
    audit_logs,
    discrepancies,
    outstanding,
    help_about
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("gripher")

BASE_DIR = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-initialize SQLite database tables and default admin on startup
    logger.info(f"Starting {settings.APP_NAME} – Initializing Database and System...")
    init_db()
    logger.info(f"{settings.APP_NAME} ready to serve requests on {settings.HOST}:{settings.PORT}")
    yield
    logger.info(f"{settings.APP_NAME} shutting down cleanly.")

app = FastAPI(
    title=settings.APP_NAME,
    version="2.4.0",
    description=settings.APP_TAGLINE,
    lifespan=lifespan
)

# Restrict CORS to local origins for security
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount static directory
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/health")
@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "tagline": settings.APP_TAGLINE,
        "version": "2.4.0"
    }

# Include Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(invoices.router)
app.include_router(payments.router)
app.include_router(reconciliation.router)
app.include_router(discrepancies.router)
app.include_router(outstanding.router)
app.include_router(reports.router)
app.include_router(settings_router.router)
app.include_router(audit_logs.router)
app.include_router(help_about.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.PORT, reload=settings.DEBUG)
