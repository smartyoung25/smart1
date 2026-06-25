"""JWT 인증 미들웨어 및 의존성 주입.

환경변수:
    JWT_SECRET_KEY   : HS256 서명 키 (필수)
    JWT_ALGORITHM    : 기본 HS256
    JWT_EXPIRE_MINUTES: 토큰 만료 분 (기본 60)

공개 경로 (인증 불필요):
    GET  /health
    POST /api/v1/auth/token
    GET  /docs, /redoc, /openapi.json

사용 예:
    @router.get("/me")
    async def get_me(user: dict = Depends(require_auth)):
        return user
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ── 설정 ──────────────────────────────────────────────────────────────────────
_SECRET_KEY     = os.environ.get("JWT_SECRET_KEY", "")
_ALGORITHM      = os.environ.get("JWT_ALGORITHM", "HS256")
_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# 공개 경로 (prefix 또는 완전 일치)
_PUBLIC_PATHS: set[str] = {
    "/health",
    "/api/v1/auth/token",
    "/api/v1/auth/demo-token",    # 공개 데모 무자격 토큰 발급
    "/api/v1/auth/register",     # 신규 회원가입
    "/api/v1/auth/password/forgot",  # 비밀번호 재설정 요청 (비인증)
    "/api/v1/auth/password/reset",   # 새 비밀번호 설정 (토큰 자체 검증)
    "/api/v1/auth/onboarding",   # 온보딩 저장 (JWT 의존성으로 별도 검증)
    "/api/v1/auth/onboarding/status",
    "/api/telemetry/client",     # 클라이언트 에러 텔레메트리(비인증 수집)
    "/api/regions",              # 행정구역 시도→시군구(공개 GET, C1 농장세팅용)
    "/api/reference",            # 기자재·시공업체 공식 참조 데이터(공개 읽기, C16 자동완성)
    "/api/cluster/overview",     # 공공기관 조회 전용 클러스터 관제(읽기)
    "/robots.txt",               # SEO 크롤러
    "/sitemap.xml",              # SEO 사이트맵
    "/manifest.webmanifest",     # PWA manifest (브라우저 비인증 로드)
    "/sw.js",                    # PWA 서비스워커
    "/icon.svg",                 # PWA 아이콘
    "/og-image.png",             # SEO 소셜 공유 카드(1200×630)
    "/docs",
    "/redoc",
    "/openapi.json",
    "/",            # 대시보드 index.html (프리뷰/단일포트)
    "/dashboard",   # 정적 파일
    "/screens",     # SmartOS 모바일 화면 (정적 HTML)
    "/components",  # SmartOS CSS/JS 컴포넌트 (정적)
    "/smartos",     # SmartOS 네비게이터
    "/index.html",  # 네비게이터 (화면들의 ../index.html 링크 대상)
    "/console",     # PC 관리자 콘솔 셸 (HTML 비인증 서빙, 안의 fetch는 토큰 필요)
    "/intro",       # 시스템 소개 인트로(랜딩)
    "/favicon.ico",
    # NOTE: '/api/data' 무인증 공개경로 제거 (보안 P0) — 생육/수확 수신·이력 GET은
    #   엔드포인트에서 require_auth + farm_id 소유권 검증함(data_collection.py).
    #   외부 IoT 센서 무인증 수집이 필요하면 X-Sensor-Key 헤더 분기로 재개방할 것.
}

_security = HTTPBearer(auto_error=False)


def _get_jwt_lib():
    """jose 또는 PyJWT를 지연 import (설치 여부에 따라 선택)."""
    try:
        from jose import jwt as jose_jwt, JWTError
        return jose_jwt, JWTError
    except ImportError:
        pass
    try:
        import jwt as pyjwt
        return pyjwt, pyjwt.PyJWTError
    except ImportError:
        return None, None


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """JWT 액세스 토큰 생성."""
    jwt_lib, _ = _get_jwt_lib()
    if jwt_lib is None:
        raise RuntimeError("python-jose 또는 PyJWT 패키지가 필요합니다.")
    if not _SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY 환경변수가 설정되지 않았습니다.")

    expire = datetime.now(tz=timezone.utc) + (
        expires_delta or timedelta(minutes=_EXPIRE_MINUTES)
    )
    payload = {**data, "exp": expire}
    return jwt_lib.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    """JWT 디코드 및 검증. 실패 시 HTTPException 발생."""
    jwt_lib, JWTError = _get_jwt_lib()
    # fail-closed: JWT 라이브러리/시크릿 미설정 시 '익명 통과'(fail-open) 대신 거부.
    #   (구: anonymous/viewer 반환 → 환경변수 누락 시 인증이 조용히 꺼지는 취약점 A1.)
    if jwt_lib is None:
        logger.critical("[auth] JWT 라이브러리 없음 — 인증 불가(fail-closed 401)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="서버 인증 구성 오류(JWT 라이브러리 없음).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _SECRET_KEY:
        logger.critical("[auth] JWT_SECRET_KEY 미설정 — 인증 불가(fail-closed 401)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="서버 인증 구성 오류(JWT_SECRET_KEY 미설정).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return jwt_lib.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"토큰 검증 실패: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """FastAPI 의존성 — Bearer 토큰 검증 후 payload 반환."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 헤더가 없습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(credentials.credentials)


_PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").lower() in ("1", "true", "yes")


async def require_admin_view(user: dict = Depends(require_auth)) -> dict:
    """admin 라우터 접근 — admin/manager는 전체 허용. 'demo' 역할은 공개 데모에서만 허용.

    데모의 파괴적·고비용 쓰기(model promote/rollback·DELETE)는 PublicDemoMiddleware가
    별도로 차단하므로, 여기서는 데모 신원이 관리자 조회·안전변경 화면(C6·C20 등)을
    이용할 수 있도록 통과시킨다. 비-데모 배포에는 'demo' 역할 자체가 발급되지 않는다.
    """
    role = user.get("role")
    if role in ("admin", "manager", "superadmin"):
        return user
    if role == "demo" and _PUBLIC_DEMO:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="관리자 권한이 필요합니다.",
    )


def require_role(role: str):
    """특정 역할 요구 의존성 팩토리.

    사용:
        @router.post("/admin")
        async def admin(user=Depends(require_role("admin"))):
    """
    async def _checker(user: dict = Depends(require_auth)) -> dict:
        if user.get("role") != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"'{role}' 권한이 필요합니다.",
            )
        return user
    return _checker


class JWTMiddleware:
    """Starlette ASGI 미들웨어 — 공개 경로 외 모든 요청에 JWT 검증 적용.

    main.py에서:
        from api.middleware.auth import JWTMiddleware
        app.add_middleware(JWTMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in _PUBLIC_PATHS):
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse

        # fail-closed: JWT_SECRET_KEY 미설정 시 보호경로를 '통과'(fail-open)시키지 않고 거부.
        #   공개 경로는 위에서 이미 통과 처리됨 → 여기 도달은 인증 필요 경로뿐.
        if not _SECRET_KEY:
            logger.critical("[auth] JWT_SECRET_KEY 미설정 — 보호경로 차단(fail-closed 401)")
            response = JSONResponse(
                {"detail": "서버 인증 구성 오류(JWT_SECRET_KEY 미설정)."},
                status_code=401, headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        request = StarletteRequest(scope, receive)
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                {"detail": "Authorization 헤더가 없거나 형식이 잘못됐습니다."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:]
        try:
            decode_token(token)
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
