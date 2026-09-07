from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from shared.config import get_settings
from shared.db import db_ping, init_db
from shared.errors import AppError, ErrorCode
from shared.logging import configure_logging, get_logger

from api.middleware import RequestIdMiddleware
from api.routes_agent import router as agent_router
from api.routes_ask import router as ask_router
from api.routes_auth import router as auth_router
from api.routes_connectors import router as connectors_router
from api.routes_documents import router as documents_router
from api.routes_governance import router as governance_router
from api.routes_graph import router as graph_router
from api.routes_learning import router as learning_router
from api.routes_scim import router as scim_router
from api.routes_search import router as search_router
from api.routes_uploads import router as uploads_router

configure_logging()
logger = get_logger("api")
settings = get_settings()

app = FastAPI(
    title="KB Agent API",
    version="0.1.0",
    description="Enterprise knowledge-base agent API",
)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(uploads_router)
app.include_router(documents_router)
app.include_router(search_router)
app.include_router(learning_router)
app.include_router(ask_router)
app.include_router(graph_router)
app.include_router(governance_router)
app.include_router(agent_router)
app.include_router(connectors_router)
app.include_router(scim_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("api_started", profile=get_settings().profile)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id,
            }
        },
        headers={"X-Request-Id": request_id},
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "profile": get_settings().profile}


@app.get("/readyz")
def readyz() -> dict:
    current = get_settings()
    db_ok = db_ping()
    checks = {
        "database": db_ok,
        "redis": "skipped" if not current.redis_url else "configured",
        "qdrant": "skipped" if not current.qdrant_url else "configured",
    }
    if not db_ok:
        raise AppError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            "database unavailable",
            status_code=503,
            details=checks,
        )
    return {"status": "ready", "checks": checks}


@app.get("/v1/meta")
def meta(request: Request) -> dict:
    current = get_settings()
    return {
        "service": "kb-agent-api",
        "version": "0.1.0",
        "profile": current.profile,
        "milestone": "Knowledge-Graph",
        "request_id": getattr(request.state, "request_id", ""),
    }
