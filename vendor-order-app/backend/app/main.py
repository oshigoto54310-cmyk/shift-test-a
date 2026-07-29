"""FastAPI アプリケーション本体。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .routers import (
    auth,
    change_requests,
    dashboard,
    exports,
    histories,
    masters,
    orders,
    vendor,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """起動時処理。開発用途ではテーブルを作成する。本番は Alembic を使う。"""
    if settings.environment != "production":
        Base.metadata.create_all(bind=engine)
        logger.info("データベーステーブルを確認しました（開発モード）")
    yield


app = FastAPI(
    title="ベンダー別・発注管理Webアプリ",
    description="スーパー本部・店舗・ベンダー間の発注業務を一元管理する業務用Webアプリ",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """XSS・クリックジャッキング対策のレスポンスヘッダを付与する。"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    )
    if settings.cookie_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """入力エラーを日本語で具体的に返す。"""
    details = []
    for err in exc.errors():
        loc = " / ".join(str(p) for p in err.get("loc", []) if p not in ("body", "query"))
        details.append(f"{loc}: {err.get('msg')}")
    return JSONResponse(
        status_code=422,
        content={"detail": "入力内容を確認してください", "errors": details},
    )


app.include_router(auth.router)
app.include_router(masters.router)
app.include_router(orders.router)
app.include_router(vendor.router)
app.include_router(change_requests.router)
app.include_router(histories.router)
app.include_router(histories.notif_router)
app.include_router(dashboard.router)
app.include_router(exports.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@app.get("/api/meta")
def meta():
    """画面で使う区分値のラベル一覧。"""
    from .constants import (
        AUDIT_ACTION_LABELS,
        CHANGE_REQUEST_STATUS_LABELS,
        NOTIFICATION_LABELS,
        ORDER_STATUS_LABELS,
        ORDER_UNIT_LABELS,
        RESPONSE_TYPE_LABELS,
        ROLE_LABELS,
    )

    return {
        "order_statuses": {str(k): v for k, v in ORDER_STATUS_LABELS.items()},
        "response_types": {str(k): v for k, v in RESPONSE_TYPE_LABELS.items()},
        "change_request_statuses": {str(k): v for k, v in CHANGE_REQUEST_STATUS_LABELS.items()},
        "roles": {str(k): v for k, v in ROLE_LABELS.items()},
        "order_units": {str(k): v for k, v in ORDER_UNIT_LABELS.items()},
        "notification_types": {str(k): v for k, v in NOTIFICATION_LABELS.items()},
        "audit_actions": {str(k): v for k, v in AUDIT_ACTION_LABELS.items()},
    }


# --------------------------------------------------------------------------
# フロントエンド（静的ファイル）の配信
# --------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """SPA のクライアントルーティング用フォールバック。"""
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "APIが見つかりません"})
        candidate = FRONTEND_DIR / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIR / "index.html"))
