"""Smart Farm API — FastAPI application entry point."""
from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.routers import farmer, admin
from api.routers.auth import router as auth_router
from api.routers.recommend_v2 import router as recommend_v2_router
from api.routers.ws import router as ws_router, _setup_mqtt_bridge
from api.routers.billing import farm_router as billing_farm_router, admin_router as billing_admin_router
from api.routers.data_collection import router as data_collection_router
from api.middleware.auth import JWTMiddleware

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="Smart Farm AI Platform",
    version="0.2.0",
    description="양방향 스마트팜 대시보드 API",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS (환경변수 기반 허용 출처) ─────────────────────────────────────────────
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000,http://localhost:8080")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── JWT 미들웨어 (JWT_SECRET_KEY 없으면 자동 비활성화) ────────────────────────
app.add_middleware(JWTMiddleware)

# ── 라우터 등록 ───────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(farmer.router)
app.include_router(admin.router)
app.include_router(recommend_v2_router)
app.include_router(ws_router)
# 빌링/구독 라우터
app.include_router(billing_farm_router,  prefix="/api/farms/{farm_id}")
app.include_router(billing_admin_router, prefix="/api/admin")
# 데이터 수집 라우터 (생육 측정값 / 수확량 실측값)
app.include_router(data_collection_router)


@app.on_event("startup")
async def startup_event():
    """앱 시작 시 MQTT→WebSocket 브리지 등록 + KAMIS 가격 갱신."""
    _setup_mqtt_bridge()

    # KAMIS 당일 가격 갱신 (백그라운드 — API 키 없으면 mock 폴백)
    import asyncio, logging as _log
    _kamis_logger = _log.getLogger("kamis_startup")
    async def _refresh_kamis():
        try:
            import sys as _sys, pathlib as _pl
            _sys.path.insert(0, str(_pl.Path(__file__).parent.parent))
            from pipeline.kamis_fetcher import refresh_prices
            loop = asyncio.get_event_loop()
            updated = await loop.run_in_executor(None, refresh_prices)
            _kamis_logger.info("[startup] KAMIS 가격 갱신 완료: %d개 작목", len(updated))
        except Exception as e:
            _kamis_logger.warning("[startup] KAMIS 갱신 실패 (무시): %s", e)
    asyncio.create_task(_refresh_kamis())


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "version": app.version}


# ── 대시보드 정적 파일 서빙 (프리뷰/단일포트 접속용) ──────────────────────────
_DASHBOARD = Path(__file__).parent.parent / "dashboard"
if _DASHBOARD.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_DASHBOARD)), name="dashboard")

    @app.get("/", include_in_schema=False)
    def serve_index():
        resp = FileResponse(str(_DASHBOARD / "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
