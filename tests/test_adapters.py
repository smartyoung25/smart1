"""어댑터 단위 테스트 — EC 단위변환, 유효범위 검증, 필드명 매핑"""
import pytest
from datetime import datetime

from adapters.base_adapter import validate_range, safe_float
from adapters.iot_sensor_adapter import adapt_row
from adapters.kamis_adapter import adapt_price_record
from adapters.wur_dataset_adapter import adapt_row as wur_adapt_row


FARM_ID = "farm_001"
NOW     = datetime(2026, 5, 9, 10, 0, 0)


# ── base_adapter ─────────────────────────────────────────────────────────────

class TestValidateRange:
    def test_temp_in_range(self):
        assert validate_range("temp_internal", 25.0) is True

    def test_temp_too_high(self):
        assert validate_range("temp_internal", 65.0) is False

    def test_temp_too_low(self):
        assert validate_range("temp_internal", -5.0) is False

    def test_unknown_variable_always_valid(self):
        assert validate_range("nonexistent_var", 99999.0) is True

    def test_humidity_boundary(self):
        assert validate_range("humidity_int", 100.0) is True
        assert validate_range("humidity_int", 100.1) is False
        assert validate_range("humidity_int", 0.0) is True


class TestSafeFloat:
    def test_numeric_string(self):
        assert safe_float("22.5") == pytest.approx(22.5)

    def test_integer(self):
        assert safe_float(10) == pytest.approx(10.0)

    def test_empty_string(self):
        assert safe_float("") is None

    def test_none(self):
        assert safe_float(None) is None

    def test_non_numeric(self):
        assert safe_float("NA") is None


# ── iot_sensor_adapter ────────────────────────────────────────────────────────

class TestIotSensorAdapter:
    def _row(self, **kwargs):
        base = {
            "온도_내부": "22.5",
            "상대습도_내부": "75",
            "잔존CO2": "900",
            "일사량_외부": "300",
            "EC": "2.1",          # mS/cm → should become 0.21 dS/m
        }
        base.update(kwargs)
        return base

    def test_ec_unit_conversion(self):
        """EC in mS/cm must be multiplied by 0.1 to get dS/m."""
        result = adapt_row(self._row(EC="2.0"), FARM_ID, NOW)
        ec_rec = next((r for r in result.records if r.canonical_name == "ec_dsm"), None)
        assert ec_rec is not None
        assert ec_rec.value == pytest.approx(0.2)

    def test_temp_maps_correctly(self):
        result = adapt_row(self._row(**{"온도_내부": "23.1"}), FARM_ID, NOW)
        temp_rec = next((r for r in result.records if r.canonical_name == "temp_internal"), None)
        assert temp_rec is not None
        assert temp_rec.value == pytest.approx(23.1)

    def test_out_of_range_skipped(self):
        """Temp = 999 should be skipped (out of valid range)."""
        result = adapt_row(self._row(**{"온도_내부": "999"}), FARM_ID, NOW)
        temp_rec = next((r for r in result.records if r.canonical_name == "temp_internal"), None)
        assert temp_rec is None
        assert any("temp_internal" in e for e in result.errors)

    def test_missing_field_skipped_gracefully(self):
        row = {"온도_내부": "22.0"}  # only one field
        result = adapt_row(row, FARM_ID, NOW)
        assert len(result.records) == 1
        assert len(result.errors) == 0

    def test_non_numeric_value_produces_error(self):
        result = adapt_row(self._row(**{"잔존CO2": "점검중"}), FARM_ID, NOW)
        assert any("co2_ppm" in e or "잔존CO2" in e for e in result.errors)

    def test_quality_tag_is_finetuned(self):
        result = adapt_row(self._row(), FARM_ID, NOW)
        for rec in result.records:
            assert rec.quality_tag == "FINETUNED"

    def test_source_id(self):
        result = adapt_row(self._row(), FARM_ID, NOW)
        for rec in result.records:
            assert rec.source_id == "iot_sensor"


# ── kamis_adapter ─────────────────────────────────────────────────────────────

class TestKamisAdapter:
    def test_basic_price(self):
        result = adapt_price_record({"가격": "3200"}, FARM_ID, NOW)
        assert len(result.records) == 1
        assert result.records[0].canonical_name == "kamis_price"
        assert result.records[0].value == pytest.approx(3200.0)

    def test_comma_separated_price(self):
        """KAMIS sometimes returns '3,200' — commas must be stripped."""
        result = adapt_price_record({"가격": "3,200"}, FARM_ID, NOW)
        assert result.records[0].value == pytest.approx(3200.0)

    def test_dpr1_field(self):
        result = adapt_price_record({"dpr1": "2800"}, FARM_ID, NOW)
        assert result.records[0].value == pytest.approx(2800.0)


# ── wur_dataset_adapter ───────────────────────────────────────────────────────

class TestWurAdapter:
    def _row(self, **kwargs):
        base = {"T_air": "21.0", "CO2_conc": "850", "I_glob": "400", "EC_solution": "2.5"}
        base.update(kwargs)
        return base

    def test_quality_tag_is_transfer(self):
        result = wur_adapt_row(self._row(), FARM_ID, NOW)
        for rec in result.records:
            assert rec.quality_tag == "TRANSFER"

    def test_ec_not_converted(self):
        """WUR EC_solution is already in dS/m — no conversion."""
        result = wur_adapt_row(self._row(EC_solution="3.0"), FARM_ID, NOW)
        ec_rec = next((r for r in result.records if r.canonical_name == "ec_dsm"), None)
        assert ec_rec is not None
        assert ec_rec.value == pytest.approx(3.0)   # unchanged

    def test_nan_skipped(self):
        result = wur_adapt_row(self._row(T_air="NaN"), FARM_ID, NOW)
        temp_rec = next((r for r in result.records if r.canonical_name == "temp_internal"), None)
        assert temp_rec is None
