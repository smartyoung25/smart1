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
        "/api/v1/auth/onboarding",                  # 농장 세팅(C1) 저장
        "/api/telemetry/client",
        "/api/data/growth", "/api/data/harvest",   # 생육·수확 실측 입력(M1/M2 학습 피드)
    }   # 로그인·회원가입·비번재설정·에러텔레메트리·학습데이터 입력
    # 사용자 데이터 입력·기록·신청 POST 허용 (운영기록 /activity 포함).
    #   ※ /api/admin/* 관리자 쓰기는 아래에서 항상 403 유지.
    _WRITE_ALLOW_SUFFIX = ("/chat", "/integration-request", "/equipment", "/climate-plan",
                           "/consent", "/daily-temp", "/whatif", "/diagnosis/checklist",
                           "/activity")
    # 경로 중간 일치 허용(예: 장비 삭제 DELETE /equipment/{device_id})
    _WRITE_ALLOW_CONTAINS = ("/equipment/",)

    class PublicDemoMiddleware:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                path = scope.get("path", ""); method = scope.get("method", "GET")
                _allow_post = ((path in _WRITE_ALLOW) or path.endswith(_WRITE_ALLOW_SUFFIX)
                               or any(c in path for c in _WRITE_ALLOW_CONTAINS))
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


# ── 대시보드 일원화: 구 PC 다크 대시보드는 비노출(모바일로 통일) ─────────────────
#   파일(dashboard/)은 보존(롤백 안전) — 라우트만 /intro 로 차단.
_DASHBOARD = Path(__file__).parent.parent / "dashboard"
if _DASHBOARD.exists():
    from starlette.responses import RedirectResponse as _Redirect

    @app.get("/", include_in_schema=False)
    def serve_index():
        return _Redirect(url="/intro", status_code=307)

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dashboard/", include_in_schema=False)
    @app.get("/dashboard/{path:path}", include_in_schema=False)
    def _block_legacy_dashboard(path: str = ""):
        # 구 PC 대시보드 전 경로 → 모바일 인트로로 일원화
        return _Redirect(url="/intro", status_code=307)

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

# 행정구역 시도→시군구 트리 (C1 농장세팅 지역 구조화 입력용)
@app.get("/api/regions", include_in_schema=False)
def serve_regions():
    # 정식 17개 시도로 정규화(개편 전후·약칭 중복 병합)
    _CANON = {
        "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
        "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
        "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
        "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
    }
    _ORDER = list(dict.fromkeys(_CANON.values()))

    def _base(sido: str) -> str | None:
        s = (sido or "").replace("특별자치도", "").replace("특별자치시", "") \
            .replace("특별시", "").replace("광역시", "").replace("도", "")
        if s.startswith("충청"): s = "충" + s[2:3]
        elif s.startswith("전라"): s = "전" + s[2:3]
        elif s.startswith("경상"): s = "경" + s[2:3]
        return s[:2] if s else None
    try:
        from api.services.region_station import _MAPPING
        tree: dict[str, set] = {v: set() for v in _ORDER}
        for (sido, sgg) in _MAPPING.keys():
            canon = _CANON.get(_base(sido))
            if not canon:
                continue
            if sgg and sgg[-1] in "시군구":
                tree[canon].add(sgg)
        out = {s: sorted(tree[s]) for s in _ORDER}
        return {"sido": _ORDER, "tree": out}
    except Exception as e:
        return {"sido": [], "tree": {}, "error": str(e)[:80]}


# 공공기관(public 역할) 조회 전용 클러스터 관제 — admin 권한 없이 읽기만 허용
@app.get("/api/cluster/overview", include_in_schema=False)
def serve_cluster_overview_public(region: str = "", crop: str = ""):
    try:
        from api.data.stats_loader import _farm_registry
        farms = (_farm_registry() or {}).get("farms", {})
    except Exception:
        farms = {}
    from api.services.cluster_overview import build_overview
    return build_overview(farms, region=region, crop=crop)


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
