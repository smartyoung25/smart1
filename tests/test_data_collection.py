"""데이터 수집 API 테스트.

POST /api/data/growth  — 주간 생육 측정값
POST /api/data/harvest — 수확량 실측값
GET  /api/data/status  — 전체 현황
GET  /api/data/status/{farm_id} — 농장별 현황
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


GROWTH_URL   = "/api/data/growth"
HARVEST_URL  = "/api/data/harvest"
STATUS_URL   = "/api/data/status"


# ── 공통 페이로드 ─────────────────────────────────────────────────────────────

GROWTH_PAYLOAD = {
    "farm_id":       "farm_001",
    "crop_ko":       "딸기",
    "recorded_date": "2026-03-15",
    "temp_internal": 22.5,
    "humidity_int":  75.0,
    "co2_ppm":       800.0,
    "solar_rad":     350.0,
    "plant_height_cm": 25.0,
    "leaf_count":    12,
    "source":        "api",
}

HARVEST_PAYLOAD = {
    "farm_id":       "farm_001",
    "crop_ko":       "딸기",
    "harvest_date":  "2026-05-10",
    "yield_kg_m2":   3.2,
    "area_m2":       500.0,
    "planting_date": "2025-10-01",
    "source":        "api",
}


# ── growth 수신 테스트 ────────────────────────────────────────────────────────

class TestGrowthEndpoint:

    def test_post_growth_ok(self, client: TestClient):
        res = client.post(GROWTH_URL, json=GROWTH_PAYLOAD)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"].startswith("stored_")
        assert "record_id" in data
        assert data["total_count"] >= 1
        assert isinstance(data["retrain_triggered"], bool)

    def test_post_growth_minimal(self, client: TestClient):
        """필수 필드만 전송해도 성공."""
        payload = {
            "farm_id":       "farm_002",
            "crop_ko":       "방울토마토",
            "recorded_date": "2026-03-20",
        }
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"].startswith("stored_")

    def test_post_growth_vpd_auto_calc(self, client: TestClient):
        """VPD 미입력 시 자동 계산 — 에러 없이 저장."""
        payload = {**GROWTH_PAYLOAD, "vpd_kpa": None, "temp_internal": 25.0, "humidity_int": 80.0}
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 200

    def test_post_growth_invalid_temp(self, client: TestClient):
        """온도 범위 초과 → 422."""
        payload = {**GROWTH_PAYLOAD, "temp_internal": 999}
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 422

    def test_post_growth_invalid_crop(self, client: TestClient):
        """crop_ko 빈 문자열 → 422."""
        payload = {**GROWTH_PAYLOAD, "crop_ko": ""}
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 422

    def test_post_growth_missing_farm_id(self, client: TestClient):
        """farm_id 누락 → 422."""
        payload = {k: v for k, v in GROWTH_PAYLOAD.items() if k != "farm_id"}
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 422

    def test_post_growth_all_env_fields(self, client: TestClient):
        """환경값 전체 입력."""
        payload = {
            **GROWTH_PAYLOAD,
            "ec_dsm": 2.0,
            "soil_temp": 18.0,
            "vpd_kpa": 0.9,
            "stem_diameter_mm": 8.5,
            "chlorophyll_spad": 42.0,
        }
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 200

    def test_post_growth_iot_auto_source(self, client: TestClient):
        """source = iot_auto."""
        payload = {**GROWTH_PAYLOAD, "source": "iot_auto"}
        res = client.post(GROWTH_URL, json=payload)
        assert res.status_code == 200


# ── harvest 수신 테스트 ───────────────────────────────────────────────────────

class TestHarvestEndpoint:

    def test_post_harvest_ok(self, client: TestClient):
        res = client.post(HARVEST_URL, json=HARVEST_PAYLOAD)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"].startswith("stored_")
        assert data["record_id"] is not None
        assert data["total_count"] >= 1

    def test_post_harvest_total_kg_auto(self, client: TestClient):
        """total_yield_kg 미입력 → 자동 계산."""
        payload = {**HARVEST_PAYLOAD, "total_yield_kg": None}
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 200

    def test_post_harvest_without_area(self, client: TestClient):
        """면적 없이 yield_kg_m2만 입력."""
        payload = {
            "farm_id": "farm_003",
            "crop_ko": "오이",
            "harvest_date": "2026-04-01",
            "yield_kg_m2": 8.5,
        }
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 200

    def test_post_harvest_growing_days_auto(self, client: TestClient):
        """planting_date + harvest_date → growing_days 자동 계산."""
        payload = {
            **HARVEST_PAYLOAD,
            "planting_date": "2025-10-01",
            "harvest_date":  "2026-05-01",
            "growing_days":  None,
        }
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 200

    def test_post_harvest_missing_yield(self, client: TestClient):
        """yield_kg_m2 누락 → 422."""
        payload = {k: v for k, v in HARVEST_PAYLOAD.items() if k != "yield_kg_m2"}
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 422

    def test_post_harvest_yield_out_of_range(self, client: TestClient):
        """yield_kg_m2 > 100 → 422."""
        payload = {**HARVEST_PAYLOAD, "yield_kg_m2": 999.0}
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 422

    def test_post_harvest_response_fields(self, client: TestClient):
        """응답 필드 검증."""
        res = client.post(HARVEST_URL, json=HARVEST_PAYLOAD)
        data = res.json()
        assert "status" in data
        assert "message_ko" in data
        assert "record_id" in data
        assert "total_count" in data
        assert "retrain_triggered" in data
        assert "retrain_message_ko" in data

    def test_post_harvest_paprika(self, client: TestClient):
        """파프리카 수확량 저장."""
        payload = {
            "farm_id":      "farm_004",
            "crop_ko":      "파프리카",
            "harvest_date": "2026-06-01",
            "yield_kg_m2":  12.5,
            "area_m2":      300.0,
        }
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 200

    def test_post_harvest_season_env(self, client: TestClient):
        """시즌 평균 환경값 포함."""
        payload = {
            **HARVEST_PAYLOAD,
            "season_avg_temp": 22.0,
            "season_avg_humidity": 74.0,
            "notes": "2025-26 시즌 정상 수확",
        }
        res = client.post(HARVEST_URL, json=payload)
        assert res.status_code == 200


# ── 재학습 트리거 테스트 ──────────────────────────────────────────────────────

class TestRetrainTrigger:

    def test_no_retrain_below_threshold(self, client: TestClient):
        """임계치 미달 시 retrain_triggered=False."""
        # 카운터를 낮게 설정 (임계치 = 10)
        import api.routers.data_collection as dc
        dc._counts["딸기"] = {"growth": 5, "harvest": 3}
        res = client.post(HARVEST_URL, json=HARVEST_PAYLOAD)
        data = res.json()
        # 4건째 → 임계치(10) 미달
        assert data["retrain_triggered"] is False

    def test_retrain_triggered_at_threshold(self, client: TestClient):
        """수확 데이터 10건 도달 시 retrain_triggered=True."""
        import api.routers.data_collection as dc
        # 9건으로 설정 → 이번 요청으로 10건 = 임계치 도달
        dc._counts["딸기"] = {"growth": 5, "harvest": 9}

        with patch("api.routers.data_collection._trigger_retrain") as mock_rt:
            mock_rt.return_value = "재학습 완료"
            res = client.post(HARVEST_URL, json=HARVEST_PAYLOAD)

        data = res.json()
        assert data["retrain_triggered"] is True

    def test_retrain_triggered_growth_threshold(self, client: TestClient):
        """생육 데이터 30건 도달 시 retrain_triggered=True."""
        import api.routers.data_collection as dc
        dc._counts["딸기"] = {"growth": 29, "harvest": 3}

        with patch("api.routers.data_collection._trigger_retrain") as mock_rt:
            mock_rt.return_value = "M1 재학습 완료"
            res = client.post(GROWTH_URL, json=GROWTH_PAYLOAD)

        data = res.json()
        assert data["retrain_triggered"] is True


# ── 상태 조회 테스트 ──────────────────────────────────────────────────────────

class TestDataStatus:

    def test_get_status_ok(self, client: TestClient):
        res = client.get(STATUS_URL)
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert "total_growth" in data
        assert "total_harvest" in data
        assert "retrain_threshold_growth" in data
        assert "retrain_threshold_harvest" in data
        assert data["retrain_threshold_harvest"] == 10
        assert data["retrain_threshold_growth"] == 30

    def test_get_status_items_structure(self, client: TestClient):
        res = client.get(STATUS_URL)
        items = res.json()["items"]
        assert len(items) >= 1
        item = items[0]
        assert "crop_ko" in item
        assert "growth_count" in item
        assert "harvest_count" in item
        assert "retrain_status" in item

    def test_get_status_farm_ok(self, client: TestClient):
        res = client.get(f"{STATUS_URL}/farm_001")
        assert res.status_code == 200
        data = res.json()
        assert data["farm_id"] == "farm_001"
        assert "items" in data

    def test_get_status_totals_nonnegative(self, client: TestClient):
        res = client.get(STATUS_URL)
        data = res.json()
        assert data["total_growth"]  >= 0
        assert data["total_harvest"] >= 0


# ── VPD 계산 유닛 테스트 ──────────────────────────────────────────────────────

class TestVpdCalculation:

    def test_vpd_calc_basic(self):
        from api.routers.data_collection import _calc_vpd
        vpd = _calc_vpd(25.0, 70.0)
        assert vpd is not None
        assert 0.5 < vpd < 1.5   # 25°C, 70% 습도 → 약 0.95 kPa

    def test_vpd_calc_none_input(self):
        from api.routers.data_collection import _calc_vpd
        assert _calc_vpd(None, 70.0) is None
        assert _calc_vpd(25.0, None) is None
        assert _calc_vpd(None, None) is None

    def test_vpd_calc_saturated(self):
        """습도 100% → VPD ≈ 0."""
        from api.routers.data_collection import _calc_vpd
        vpd = _calc_vpd(20.0, 100.0)
        assert vpd == pytest.approx(0.0, abs=0.01)

    def test_vpd_calc_dry(self):
        """낮은 습도 → 높은 VPD."""
        from api.routers.data_collection import _calc_vpd
        vpd = _calc_vpd(30.0, 40.0)
        assert vpd is not None
        assert vpd > 2.0   # 30°C, 40% 습도 → 약 2.5 kPa


# ── JSON 저장 폴백 테스트 ─────────────────────────────────────────────────────

class TestJsonFallback:

    def test_json_file_created(self, tmp_path, monkeypatch):
        """DB 없을 때 JSON 파일 생성 확인."""
        from api.routers import data_collection as dc

        monkeypatch.setattr(dc, "_GROWTH_DIR",  tmp_path / "growth")
        monkeypatch.setattr(dc, "_HARVEST_DIR", tmp_path / "harvest")

        record = {
            "id": "test-uuid",
            "farm_id": "farm_x",
            "crop_ko": "딸기",
            "recorded_at": "2026-01-01T00:00:00+00:00",
        }
        rec_id = dc._save_to_json(tmp_path / "growth", "딸기", record)
        saved = list((tmp_path / "growth").glob("딸기_*.json"))
        assert len(saved) == 1
        data = json.loads(saved[0].read_text(encoding="utf-8"))
        assert data["farm_id"] == "farm_x"

    def test_count_files(self, tmp_path):
        """파일 카운트 함수 검증."""
        from api.routers import data_collection as dc

        d = tmp_path / "harvest"
        d.mkdir()
        (d / "딸기_aaa.json").write_text("{}", encoding="utf-8")
        (d / "딸기_bbb.json").write_text("{}", encoding="utf-8")
        (d / "오이_ccc.json").write_text("{}", encoding="utf-8")

        assert dc._count_files(d, "딸기") == 2
        assert dc._count_files(d, "오이") == 1
        assert dc._count_files(d, "파프리카") == 0
