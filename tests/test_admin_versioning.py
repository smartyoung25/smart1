"""Admin 모델 버전 관리 API 통합 테스트."""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


class TestModelVersionsAPI:
    """GET /api/admin/models/versions — 빈 레지스트리에서도 200 반환."""

    def test_versions_empty_registry(self, admin_client: TestClient):
        with patch("pipeline.model_registry._load_registry", return_value={}):
            res = admin_client.get("/api/admin/models/versions?crop_en=strawberry")
        assert res.status_code == 200
        data = res.json()
        assert data["crop_en"] == "strawberry"
        assert data["versions"] == []
        assert data["active_version"] is None

    def test_versions_with_data(self, admin_client: TestClient):
        fake_reg = {
            "strawberry": {
                "active_version": 2,
                "versions": [
                    {
                        "version": 1, "timestamp": "2026-01-01T00:00:00+00:00",
                        "triggered_by": "retrain", "mape_stage2": 8.1,
                        "mape_stage3": 9.5, "cv_r2": 0.81, "gate_passed": True,
                        "is_active": False, "snapshot_version": None,
                    },
                    {
                        "version": 2, "timestamp": "2026-02-01T00:00:00+00:00",
                        "triggered_by": "retrain", "mape_stage2": 5.2,
                        "mape_stage3": 6.1, "cv_r2": 0.91, "gate_passed": True,
                        "is_active": True, "snapshot_version": 1,
                    },
                ],
            }
        }
        with patch("pipeline.model_registry._load_registry", return_value=fake_reg):
            res = admin_client.get("/api/admin/models/versions?crop_en=strawberry")

        assert res.status_code == 200
        data = res.json()
        assert data["active_version"] == 2
        assert len(data["versions"]) == 2
        # 최신순 — version 2가 먼저
        assert data["versions"][0]["version"] == 2

    def test_versions_requires_admin_auth(self, client: TestClient):
        res = client.get("/api/admin/models/versions?crop_en=strawberry")
        assert res.status_code == 401


class TestAllVersionsAPI:
    def test_all_versions_returns_all_crops(self, admin_client: TestClient):
        with patch("pipeline.model_registry._load_registry", return_value={}):
            res = admin_client.get("/api/admin/models/versions/all")
        assert res.status_code == 200
        data = res.json()
        assert "crops" in data
        # 5작목 + 오이(cucumber)
        assert len(data["crops"]) >= 5


class TestRollbackAPI:
    def test_rollback_success(self, admin_client: TestClient):
        fake_reg = {
            "strawberry": {
                "active_version": 1,
                "versions": [
                    {
                        "version": 1, "timestamp": "2026-01-01T00:00:00+00:00",
                        "triggered_by": "retrain", "mape_stage2": 5.0,
                        "mape_stage3": 6.0, "cv_r2": 0.90, "gate_passed": True,
                        "is_active": True, "snapshot_version": None,
                    }
                ],
            }
        }
        with patch("pipeline.model_registry.rollback", return_value=True) as mock_rb, \
             patch("pipeline.model_registry._load_registry", return_value=fake_reg):
            res = admin_client.post(
                "/api/admin/models/rollback",
                json={"crop_en": "strawberry", "target_version": 1},
            )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["crop_en"] == "strawberry"

    def test_rollback_failure(self, admin_client: TestClient):
        with patch("pipeline.model_registry.rollback", return_value=False), \
             patch("pipeline.model_registry._load_registry", return_value={}):
            res = admin_client.post(
                "/api/admin/models/rollback",
                json={"crop_en": "strawberry"},
            )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False

    def test_rollback_requires_admin_auth(self, client: TestClient):
        res = client.post("/api/admin/models/rollback", json={"crop_en": "strawberry"})
        assert res.status_code == 401


class TestCompareAPI:
    def test_compare_versions(self, admin_client: TestClient):
        fake_result = {
            "crop_en": "strawberry",
            "version_a": {"version": 1, "mape_stage2": 8.0, "cv_r2": 0.80},
            "version_b": {"version": 2, "mape_stage2": 5.0, "cv_r2": 0.90},
            "delta": {"mape_stage2": -3.0, "mape_stage3": None, "cv_r2": 0.10},
        }
        with patch("pipeline.model_registry.compare_versions", return_value=fake_result):
            res = admin_client.get(
                "/api/admin/models/compare"
                "?crop_en=strawberry&version_a=1&version_b=2"
            )
        assert res.status_code == 200
        data = res.json()
        assert data["delta"]["mape_stage2"] == pytest.approx(-3.0)
        assert data["delta"]["cv_r2"]        == pytest.approx(0.10)

    def test_compare_invalid_versions_returns_404(self, admin_client: TestClient):
        with patch("pipeline.model_registry.compare_versions",
                   return_value={"error": "버전 없음"}):
            res = admin_client.get(
                "/api/admin/models/compare"
                "?crop_en=strawberry&version_a=1&version_b=99"
            )
        assert res.status_code == 404
