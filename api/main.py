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
from api.routers.telemetry import router as telemetry_router
from api.routers.federated import router as federated_router
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

# ── 공개 데모(읽기 전용) 모드 ─────────────────────────────────────────────────
# PUBLIC_DEMO=1 이면 외부 공개 시 안전하도록:
#   · 모든 쓰기(POST/PUT/PATCH/DELETE) 차단 (단 로그인 토큰 발급은 허용)
#   · /api/admin/* 전면 차단
# → 누구나 데모 데이터를 '볼' 수만 있고, 변경·삭제·관리자 접근은 불가.
_PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").lower() in ("1", "true", "yes")
if _PUBLIC_DEMO:
    from starlette.responses import JSONResponse as _JSONResp
    _WRITE = {"POST", "PUT", "PATCH", "DELETE"}
    _WRITE_ALLOW = {
        "/api/v1/auth/token", "/api/v1/auth/register",
        "/api/v1/auth/password/forgot", "/api/v1/auth/password/reset",
        "/api/telemetry/client",
    }   # 로그인·회원가입·비번재설정·에러텔레메트리만 허용
    # 조회성/신청·등록성 POST: AI 챗봇(/chat)·연동신청(/integration-request)·장비등록(/equipment)
    # — 온보딩·신청 성격으로 농장 운영데이터(관수·수확 등)는 변경하지 않음
    _WRITE_ALLOW_SUFFIX = ("/chat", "/integration-request", "/equipment", "/climate-plan", "/consent", "/daily-temp")

    class PublicDemoMiddleware:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                path = scope.get("path", ""); method = scope.get("method", "GET")
                _allow_post = (path in _WRITE_ALLOW) or path.endswith(_WRITE_ALLOW_SUFFIX)
                blocked = (
                    (path.startswith("/api/admin")) or
                    (method in _WRITE and path.startswith("/api/") and not _allow_post)
                )
                if blocked:
                    resp = _JSONResp(
                        {"detail": "공개 데모(읽기 전용) 모드입니다. 변경·관리자 기능은 비활성화되어 있습니다."},
                        status_code=403)
                    await resp(scope, receive, send); return
            await self.app(scope, receive, send)

    app.add_middleware(PublicDemoMiddleware)
    import logging as _lg; _lg.getLogger("uvicorn").warning("[main] PUBLIC_DEMO 읽기전용 모드 활성")

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
app.include_router(telemetry_router)
app.include_router(federated_router)


@app.on_event("startup")
async def startup_event():
    """앱 시작 시 MQTT→WebSocket 브리지 등록 + KAMIS 가격 갱신 + 일일 갱신 스케줄."""
    _setup_mqtt_bridge()

    import asyncio, logging as _log
    _kamis_logger = _log.getLogger("kamis_startup")

    async def _refresh_kamis_once():
        try:
            from pipeline.kamis_fetcher import refresh_prices
            loop = asyncio.get_event_loop()
            updated = await loop.run_in_executor(None, refresh_prices)
            _kamis_logger.info("[kamis] 가격 갱신 완료: %d개 작목", len(updated))
        except Exception as e:
            _kamis_logger.warning("[kamis] 갱신 실패 (무시): %s", e)

    async def _daily_kamis_scheduler():
        """매일 오전 7시 KAMIS 가격 자동 갱신 (KAMIS 도매시장 오전 개장 반영)."""
        from datetime import datetime, timezone, timedelta
        await asyncio.sleep(2)  # 시작 시 즉시 1회 갱신
        await _refresh_kamis_once()
        while True:
            now = datetime.now(tz=timezone(timedelta(hours=9)))  # KST
            # 다음 오전 7시까지 대기
            next_run = now.replace(hour=7, minute=0, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)
            wait_secs = (next_run - now).total_seconds()
            _kamis_logger.info("[kamis] 다음 자동 갱신: %s (%.0f초 후)",
                               next_run.strftime("%Y-%m-%d %H:%M KST"), wait_secs)
            await asyncio.sleep(wait_secs)
            await _refresh_kamis_once()

    asyncio.create_task(_daily_kamis_scheduler())


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

# ── SmartOS 모바일 화면 정적 서빙 (/screens, /components, /index.html) ─────────
_SMARTOS_ROOT = Path(__file__).parent.parent
for _sub in ("screens", "components"):
    _p = _SMARTOS_ROOT / _sub
    if _p.exists():
        app.mount(f"/{_sub}", StaticFiles(directory=str(_p)), name=_sub)

# SmartOS 네비게이터 index.html 직접 서빙
_SMARTOS_INDEX = _SMARTOS_ROOT / "index.html"
if _SMARTOS_INDEX.exists():
    @app.get("/smartos", include_in_schema=False)
    @app.get("/smartos/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)   # 화면들의 ../index.html 링크 대상
    def serve_smartos_index():
        return FileResponse(str(_SMARTOS_INDEX))

# 시스템 소개 인트로(랜딩) 페이지
_INTRO = _SMARTOS_ROOT / "screens" / "intro.html"
if _INTRO.exists():
    @app.get("/intro", include_in_schema=False)
    @app.get("/intro/", include_in_schema=False)
    def serve_intro():
        return FileResponse(str(_INTRO))

# PWA — manifest·service worker·아이콘 (루트 스코프로 전 화면 제어)
@app.get("/manifest.webmanifest", include_in_schema=False)
def serve_manifest():
    return FileResponse(str(_SMARTOS_ROOT / "manifest.webmanifest"), media_type="application/manifest+json")

@app.get("/sw.js", include_in_schema=False)
def serve_sw():
    # SW는 루트 스코프 제어를 위해 캐시 무효화 헤더와 함께 서빙
    return FileResponse(str(_SMARTOS_ROOT / "sw.js"), media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

@app.get("/icon.svg", include_in_schema=False)
def serve_icon():
    return FileResponse(str(_SMARTOS_ROOT / "icon.svg"), media_type="image/svg+xml")
