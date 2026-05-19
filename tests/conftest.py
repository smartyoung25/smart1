"""pytest 공통 픽스처 — JWT 인증 포함 통합 테스트 지원.

환경변수를 모듈 임포트 *이전*에 설정해야 _SECRET_KEY 등이 올바르게 로드됩니다.
conftest.py가 가장 먼저 실행되는 특성을 활용합니다.
"""
from __future__ import annotations

import os

# ── 테스트 환경변수 (모듈 임포트 전에 설정) ────────────────────────────────────
# DATABASE_URL을 빈 문자열로 설정 → _get_engine()이 즉시 None 반환 (인메모리 폴백)
# load_dotenv(override=False)는 기존 값을 덮어쓰지 않으므로 .env보다 이 설정이 우선
os.environ["DATABASE_URL"]      = ""

os.environ["JWT_SECRET_KEY"]    = "test-secret-key-pytest-only"
os.environ["JWT_EXPIRE_MINUTES"]= "60"
os.environ["ADMIN_USERNAME"]    = "admin"
os.environ["ADMIN_PASSWORD"]    = "testpassword"
os.environ["ALLOWED_ORIGINS"]  = "http://localhost"
os.environ["LOG_LEVEL"]         = "warning"

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.middleware.auth import create_access_token


# ── 기본 클라이언트 ───────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def client() -> TestClient:
    """인증 헤더 없는 기본 TestClient."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── JWT 토큰 픽스처 ──────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def admin_token() -> str:
    return create_access_token({"sub": "admin", "role": "admin"})


@pytest.fixture(scope="session")
def viewer_token() -> str:
    return create_access_token({"sub": "viewer", "role": "viewer"})


# ── 인증 헤더 픽스처 ─────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def viewer_headers(viewer_token: str) -> dict:
    return {"Authorization": f"Bearer {viewer_token}"}


# ── 인증된 클라이언트 픽스처 ─────────────────────────────────────────────────
@pytest.fixture(scope="session")
def admin_client(admin_headers: dict) -> TestClient:
    """모든 요청에 admin Bearer 헤더를 자동 첨부하는 TestClient."""
    with TestClient(app, headers=admin_headers, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="session")
def farmer_client(viewer_headers: dict) -> TestClient:
    """Farmer(공개) 엔드포인트용 — viewer 토큰으로 JWT 미들웨어 통과."""
    with TestClient(app, headers=viewer_headers, raise_server_exceptions=True) as c:
        yield c
