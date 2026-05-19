"""FastAPI 통합 테스트 — JWT 인증 포함.

Farmer 엔드포인트: 인증 불필요 (공개 API)
Admin 엔드포인트: admin JWT 필요
Pipeline 엔드포인트: admin JWT 필요
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── /health ──────────────────────────────────────────────────────────────────

def test_health(client: TestClient):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body


# ── Farmer 엔드포인트 (공개) ──────────────────────────────────────────────────

class TestFarmerEndpoints:
    FARM_ID = "farm_001"

    def test_summary_ok(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["farm_id"] == self.FARM_ID
        assert "alert_count" in data
        assert "harvest_days_remaining" in data
        assert "revenue_mtd_krw" in data

    def test_recommendations_ok(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/recommendations")
        assert res.status_code == 200
        data = res.json()
        assert "recommendations" in data
        assert len(data["recommendations"]) >= 1

    def test_recommendations_structure(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/recommendations")
        rec = res.json()["recommendations"][0]
        assert "rank" in rec
        assert "action_ko" in rec
        assert "profit_delta" in rec
        assert "tier_action" in rec
        assert rec["tier_action"] in ("checklist", "approval_required", "auto")

    def test_recommendations_sorted_by_rank(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/recommendations")
        ranks = [r["rank"] for r in res.json()["recommendations"]]
        assert ranks == sorted(ranks)

    def test_apply_manual_farm_returns_checklist(self, farmer_client: TestClient):
        res = farmer_client.post(
            f"/api/farms/{self.FARM_ID}/apply",
            json={"rank": 1, "confirmed": False},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "checklist_generated"
        assert "checklist_url" in data

    def test_apply_semi_auto_without_confirmed_returns_approval_required(self, farmer_client: TestClient):
        res = farmer_client.post(
            "/api/farms/farm_002/apply",
            json={"rank": 1, "confirmed": False},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "approval_required"

    def test_apply_semi_auto_with_confirmed_returns_sent(self, farmer_client: TestClient):
        res = farmer_client.post(
            "/api/farms/farm_002/apply",
            json={"rank": 1, "confirmed": True},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "sent"

    def test_environment_ok(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/environment")
        assert res.status_code == 200
        data = res.json()
        assert "measurements" in data
        assert len(data["measurements"]) > 0

    def test_environment_has_quality_tag(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/environment")
        for m in res.json()["measurements"]:
            assert m["quality_tag"] in ("FINETUNED", "TRANSFER", "SIMULATION", "LITERATURE")

    def test_harvest_ok(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/harvest")
        assert res.status_code == 200
        data = res.json()
        assert "predicted_date" in data
        assert "predicted_yield_kg_m2" in data
        assert "confidence" in data

    def test_revenue_ok(self, farmer_client: TestClient):
        res = farmer_client.get(f"/api/farms/{self.FARM_ID}/revenue")
        assert res.status_code == 200
        data = res.json()
        assert "kamis_price_krw_kg" in data
        assert "predicted_profit_krw" in data

    def test_unknown_farm_returns_404(self, farmer_client: TestClient):
        res = farmer_client.get("/api/farms/farm_999/summary")
        assert res.status_code == 404


# ── Admin 엔드포인트 (JWT admin 필요) ─────────────────────────────────────────

class TestAdminEndpoints:
    """admin_client 픽스처 사용 — 모든 요청에 admin 헤더 자동 첨부."""

    def test_overview_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/overview")
        assert res.status_code == 200
        data = res.json()
        assert "connected_farms" in data
        assert "avg_model_r2" in data

    def test_models_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/models")
        assert res.status_code == 200
        models = res.json()["models"]
        assert len(models) > 0
        for m in models:
            assert "module_id" in m
            assert "passed" in m
            assert isinstance(m["passed"], bool)

    def test_data_sources_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/data-sources")
        assert res.status_code == 200
        sources = res.json()["sources"]
        source_ids = [s["source_id"] for s in sources]
        assert "iot_sensor" in source_ids
        assert "kamis" in source_ids

    def test_variable_registry_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/variable-registry")
        assert res.status_code == 200
        variables = res.json()["variables"]
        names = [v["canonical_name"] for v in variables]
        assert "temp_internal" in names
        assert "ec_dsm" in names

    def test_pipeline_runs_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/pipeline/runs")
        assert res.status_code == 200
        assert "runs" in res.json()

    def test_pipeline_trigger_returns_run_id(self, admin_client: TestClient):
        res = admin_client.post("/api/admin/pipeline/trigger", json={"reason": "test"})
        assert res.status_code == 200
        data = res.json()
        assert "run_id" in data
        assert data["status"] == "queued"

    def test_pipeline_state_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/pipeline/state")
        assert res.status_code == 200
        data = res.json()
        # 파이프라인 상태 파일이 없어도 기본값 반환
        assert "crops" in data or "detail" not in data

    def test_retrain_history_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/pipeline/retrain-history")
        assert res.status_code == 200
        data = res.json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_etl_status_ok(self, admin_client: TestClient):
        res = admin_client.get("/api/admin/pipeline/etl-status")
        assert res.status_code == 200
        data = res.json()
        assert "done_files" in data
        assert isinstance(data["done_files"], int)
