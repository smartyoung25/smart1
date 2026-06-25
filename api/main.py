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
import api.routers.farmer_irrigation  # noqa: F401 — side-effect: registers irrigation+field routes on farmer router
import api.routers.farmer_pdca        # noqa: F401 — side-effect: registers PDCA routes on farmer router
import api.routers.farmer_equipment   # noqa: F401 — side-effect: registers equipment·consent·integration routes
import api.routers.farmer_env          # noqa: F401 — side-effect: registers climate-plan routes
from api.routers.auth import router as auth_router
from api.routers.recommend_v2 import router as recommend_v2_router
from api.routers.ws import router as ws_router, _setup_mqtt_bridge
from api.routers.billing import farm_router as billing_farm_router, admin_router as billing_admin_router
from api.routers.data_collection import router as data_collection_router
from api.routers.telemetry import router as telemetry_router
from api.routers.federated import router as federated_router
from api.routers.reference import router as reference_router
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
        "/api/v1/auth/token", "/api/v1/auth/demo-token", "/api/v1/auth/register",
        "/api/v1/auth/password/forgot", "/api/v1/auth/password/reset",
        "/api/v1/auth/onboarding",                  # 농장 세팅(C1) 저장
        "/api/telemetry/client",
        "/api/data/growth", "/api/data/harvest",   # 생육·수확 실측 입력(M1/M2 학습 피드)
        "/api/v2/recommend",                        # AI 추천 생성(무변경 읽기 — 메서드만 POST)
    }   # 로그인·회원가입·비번재설정·에러텔레메트리·학습데이터 입력·추천
    # 사용자 데이터 입력·기록·신청 POST 허용 (운영기록 /activity 포함).
    #   ※ /api/admin/* 관리자 쓰기는 아래에서 항상 403 유지.
    _WRITE_ALLOW_SUFFIX = ("/chat", "/integration-request", "/equipment", "/climate-plan",
                           "/consent", "/daily-temp", "/whatif", "/whatif/multi",
                           "/diagnosis/checklist",
                           "/activity", "/irrigation",   # /irrigation: G3 일일 관수 기록 입력
                           "/environment/manual")        # G2 환경 실측 수동 입력·수정
    # 경로 중간 일치 허용(예: 장비 삭제 DELETE /equipment/{device_id})
    #   /whatif·/whatif/multi 는 _WRITE_ALLOW_SUFFIX(endswith)가 정확히 커버하므로
    #   부분문자열 매칭에서 제외(과허용 방지 — 예: /whatif-admin 미래경로 차단).
    _WRITE_ALLOW_CONTAINS = ("/equipment/",)

    class PublicDemoMiddleware:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                path = scope.get("path", ""); method = scope.get("method", "GET")
                _allow_post = ((path in _WRITE_ALLOW) or path.endswith(_WRITE_ALLOW_SUFFIX)
                               or any(c in path for c in _WRITE_ALLOW_CONTAINS))
                if path.startswith("/api/admin"):
                    # 불변식: 공개 데모에서 /api/admin/* 쓰기는 전부 403.
                    #   조회(GET/HEAD)는 통과 → C6·C20 등 관리자 조회화면 시연 가능.
                    #   (구 deny-list는 promote/rollback/DELETE 외 모든 admin 쓰기를 통과시켜
                    #    billing/set-tier·cluster/notify·prices/refresh 누출 → 전면 차단으로 복원.)
                    blocked = method in _WRITE
                    deny_msg = "관리자 쓰기는 공개 데모에서 비활성화되어 있습니다."
                else:
                    blocked = (method in _WRITE and path.startswith("/api/") and not _allow_post)
                    deny_msg = "공개 데모(읽기 전용) 모드입니다. 일반 입력·기록은 가능하나 이 변경은 비활성화되어 있습니다."
                if blocked:
                    await _JSONResp({"detail": deny_msg}, status_code=403)(scope, receive, send); return
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
# 기자재·시공업체 공식 참조 데이터(읽기 전용)
app.include_router(reference_router)


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
    from api.services.persistence import _ENGINE_FAILED
    db_ok = not _ENGINE_FAILED
    if not db_ok:
        import logging
        logging.getLogger(__name__).critical(
            "DB 미연결 — in-memory 폴백 중. 수동입력 데이터 재시작 시 소멸 위험."
        )
    return {"status": "ok", "version": app.version, "db_ok": db_ok}


# ── 대시보드 일원화: 구 PC 다크 대시보드는 비노출(모바일로 통일) ─────────────────
#   구 dashboard/는 archive/dashboard/로 이관(죽은 코드). 라우트는 항상 /intro로 차단.
#   (dashboard/ 존재 여부와 무관하게 '/'·차단 라우트를 등록 — 이관 후에도 루트 정상.)
from starlette.responses import RedirectResponse as _Redirect


@app.get("/", include_in_schema=False)
def serve_index():
    # SEO: 루트를 intro.html 직접 서빙(200) — canonical=/ 와 신호 일치
    # (구: /intro 307 리다이렉트 → 색인 신호 분산). intro head의 canonical이 / 라
    # 중복콘텐츠(/intro)는 정규화됨.
    _intro = Path(__file__).parent.parent / "screens" / "intro.html"
    if _intro.exists():
        return FileResponse(str(_intro))
    return _Redirect(url="/intro", status_code=307)


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/", include_in_schema=False)
@app.get("/dashboard/{path:path}", include_in_schema=False)
def _block_legacy_dashboard(path: str = ""):
    # 구 PC 대시보드 전 경로 → 모바일 인트로로 일원화(archive 이관 후에도 차단 유지)
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

# PC 관리자 콘솔 셸 (admin/manager 전용 풀폭 레이아웃)
_CONSOLE = _SMARTOS_ROOT / "console.html"
if _CONSOLE.exists():
    @app.get("/console", include_in_schema=False)
    @app.get("/console/", include_in_schema=False)
    def serve_console():
        return FileResponse(str(_CONSOLE))

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
    # 정식 17개 시도로 정규화(개편 전후·약칭 중복 병합) — region_canon 단일 소스
    from api.services.region_canon import SIDO_ORDER, canonical_sido_or_none
    try:
        from api.services.region_station import _MAPPING
        tree: dict[str, set] = {v: set() for v in SIDO_ORDER}
        for (sido, sgg) in _MAPPING.keys():
            canon = canonical_sido_or_none(sido)
            if not canon:
                continue
            if sgg and sgg[-1] in "시군구":
                tree[canon].add(sgg)
        out = {s: sorted(tree[s]) for s in SIDO_ORDER}
        return {"sido": SIDO_ORDER, "tree": out}
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
    # 무인증 공개 경로 → 개별 farm_id를 익명 해시 프록시로(P1 PII 역추적 차단)
    return build_overview(farms, region=region, crop=crop, anonymize=True)


# SEO — robots.txt / sitemap.xml (검색엔진 크롤링)
@app.get("/robots.txt", include_in_schema=False)
def serve_robots():
    return FileResponse(str(_SMARTOS_ROOT / "robots.txt"), media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def serve_sitemap():
    return FileResponse(str(_SMARTOS_ROOT / "sitemap.xml"), media_type="application/xml")


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

@app.get("/og-image.png", include_in_schema=False)
def serve_og_image():
    # SEO/소셜 공유 카드(1200×630) — Open Graph·Twitter Card 썸네일
    return FileResponse(str(_SMARTOS_ROOT / "og-image.png"), media_type="image/png")
