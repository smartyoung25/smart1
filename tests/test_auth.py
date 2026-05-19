"""JWT 인증 엔드포인트 통합 테스트.

테스트 범위:
  - POST /api/v1/auth/token  (정상 로그인 / 잘못된 자격증명)
  - Admin 엔드포인트 접근 제어 (인증 없음 → 401, viewer → 403, admin → 200)
  - 토큰 포맷 검증
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


ADMIN_USER = "admin"
ADMIN_PASS = "testpassword"
TOKEN_URL  = "/api/v1/auth/token"


# ── 토큰 발급 ─────────────────────────────────────────────────────────────────

class TestTokenIssuance:
    def test_valid_credentials_return_token(self, client: TestClient):
        res = client.post(TOKEN_URL, json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert res.status_code == 200, res.text
        data = res.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_token_is_non_empty_string(self, client: TestClient):
        res = client.post(TOKEN_URL, json={"username": ADMIN_USER, "password": ADMIN_PASS})
        token = res.json()["access_token"]
        assert isinstance(token, str) and len(token) > 20

    def test_wrong_password_returns_401(self, client: TestClient):
        res = client.post(TOKEN_URL, json={"username": ADMIN_USER, "password": "wrong"})
        assert res.status_code == 401

    def test_unknown_user_returns_401(self, client: TestClient):
        res = client.post(TOKEN_URL, json={"username": "nobody", "password": "x"})
        assert res.status_code == 401

    def test_missing_fields_returns_422(self, client: TestClient):
        res = client.post(TOKEN_URL, json={"username": ADMIN_USER})
        assert res.status_code == 422


# ── Admin 접근 제어 ───────────────────────────────────────────────────────────

class TestAdminAccessControl:
    OVERVIEW_URL = "/api/admin/overview"

    def test_no_token_returns_401(self, client: TestClient):
        res = client.get(self.OVERVIEW_URL)
        assert res.status_code == 401

    def test_viewer_token_returns_403(self, client: TestClient, viewer_headers: dict):
        res = client.get(self.OVERVIEW_URL, headers=viewer_headers)
        assert res.status_code == 403

    def test_admin_token_returns_200(self, client: TestClient, admin_headers: dict):
        res = client.get(self.OVERVIEW_URL, headers=admin_headers)
        assert res.status_code == 200

    def test_malformed_bearer_returns_401(self, client: TestClient):
        res = client.get(self.OVERVIEW_URL, headers={"Authorization": "Bearer notajwt"})
        assert res.status_code == 401

    def test_wrong_scheme_returns_401(self, client: TestClient, admin_token: str):
        """Basic 스킴으로 JWT를 보내도 거부."""
        res = client.get(self.OVERVIEW_URL, headers={"Authorization": f"Basic {admin_token}"})
        assert res.status_code == 401


# ── 공개 경로는 토큰 없이 접근 가능 ──────────────────────────────────────────

class TestPublicPaths:
    def test_health_no_auth(self, client: TestClient):
        assert client.get("/health").status_code == 200

    def test_docs_no_auth(self, client: TestClient):
        assert client.get("/docs").status_code == 200

    def test_openapi_no_auth(self, client: TestClient):
        assert client.get("/openapi.json").status_code == 200
