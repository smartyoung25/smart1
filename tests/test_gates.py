"""게이트 단일 정책(pipeline/gates.py) 회귀 테스트.

배경: MAPE가 4곳(stage2_meta[권위]·pipeline_meta·registry·pkl 내부)에 기록되고
값이 조용히 어긋나 게이트·블렌딩·보고서가 동시에 틀어진 사고가 있었음.
이 테스트는 (1) 판정 규칙 (2) 권위 로딩 (3) fail-open (4) 괴리 감지를 고정한다.
"""
from __future__ import annotations

import json

import pytest

from pipeline.gates import (
    CV_R2_MIN, MAPE_FALLBACK, MAPE_SERVE, N_MIN,
    check_consistency, evaluate_crop, evaluate_m2_gate,
    passes_gate, read_stage2_metrics, should_serve_m2,
)


def _write_meta(tmp_path, crop_en, stage2_meta=None, pipeline_meta=None):
    d = tmp_path / "models" / "artifacts" / crop_en
    d.mkdir(parents=True, exist_ok=True)
    if stage2_meta is not None:
        (d / "stage2_meta.json").write_text(json.dumps(stage2_meta), encoding="utf-8")
    if pipeline_meta is not None:
        (d / "pipeline_meta.json").write_text(json.dumps(pipeline_meta), encoding="utf-8")
    return tmp_path / "models" / "artifacts"


class TestEvaluateM2Gate:
    def test_serve_when_mape_and_r2_ok(self):
        r = evaluate_m2_gate(17.8, 0.295, 6427)
        assert r["verdict"] == "serve" and r["serve_m2"] is True

    def test_fallback_when_mape_over_threshold(self):
        r = evaluate_m2_gate(63.9, 0.592, 42)
        assert r["verdict"] == "fallback" and r["serve_m2"] is False

    def test_conditional_when_mape_borderline(self):
        r = evaluate_m2_gate(29.2, 0.802, 48)
        assert r["verdict"] == "conditional" and r["serve_m2"] is True

    def test_conditional_when_r2_too_low(self):
        """완숙토마토 사례: MAPE는 경계인데 설명력(R²)이 거의 0."""
        r = evaluate_m2_gate(28.1, 0.099, 177)
        assert r["verdict"] == "conditional"
        assert any("R²" in x for x in r["reasons"])

    def test_overfit_gap_forces_conditional(self):
        r = evaluate_m2_gate(10.0, 0.30, 500, train_r2=0.95)
        assert r["verdict"] == "conditional"

    def test_small_sample_flagged_but_verdict_kept(self):
        """오이 사례: n=30 이지만 지표가 좋아 서빙 — 플래그만 남긴다."""
        r = evaluate_m2_gate(22.8, 0.826, 30)
        assert r["verdict"] == "serve"
        assert r["flags"] and "소표본" in r["flags"][0]

    def test_none_mape_is_fallback(self):
        assert evaluate_m2_gate(None)["serve_m2"] is False

    def test_boundaries(self):
        assert evaluate_m2_gate(MAPE_SERVE, 0.5, 100)["verdict"] == "serve"
        assert evaluate_m2_gate(MAPE_FALLBACK, 0.5, 100)["verdict"] == "conditional"
        assert evaluate_m2_gate(MAPE_FALLBACK + 0.1, 0.5, 100)["verdict"] == "fallback"
        assert evaluate_m2_gate(10.0, CV_R2_MIN - 0.01, 100)["verdict"] == "conditional"

    def test_passes_gate_alias(self):
        assert passes_gate(17.8, 0.3, 100) is True
        assert passes_gate(63.9, 0.5, 100) is False


class TestAuthoritativeLoading:
    def test_stage2_meta_overrides_pipeline_meta(self, tmp_path):
        """★ 핵심: 참외 사례 — pipeline_meta 8.7 vs stage2_meta 63.9 → 권위값 채택."""
        arts = _write_meta(
            tmp_path, "melon",
            stage2_meta={"mape": 63.9, "cv_r2_mean": 0.592, "n_train": 42},
            pipeline_meta={"stage2": {"mape": 8.7, "cv_r2_mean": 0.225, "n_train": 84}},
        )
        m = read_stage2_metrics(arts, "melon")
        assert m["mape"] == 63.9 and m["n_train"] == 42

    def test_evaluate_crop_uses_authority(self, tmp_path):
        arts = _write_meta(
            tmp_path, "melon",
            stage2_meta={"mape": 63.9, "cv_r2_mean": 0.592, "n_train": 42},
            pipeline_meta={"stage2": {"mape": 8.7}},
        )
        assert evaluate_crop(arts, "melon")["verdict"] == "fallback"

    def test_pipeline_meta_used_when_no_stage2_meta(self, tmp_path):
        arts = _write_meta(tmp_path, "x", pipeline_meta={"stage2": {"mape": 12.0, "cv_r2_mean": 0.5}})
        assert read_stage2_metrics(arts, "x")["mape"] == 12.0

    def test_missing_files_return_empty(self, tmp_path):
        assert read_stage2_metrics(tmp_path, "nope") == {}


class TestShouldServeFailOpen:
    def test_fail_open_when_no_metrics(self, tmp_path):
        """지표 없는 구 아티팩트를 게이트가 차단하면 안 된다(기존 동작 유지)."""
        ok, v = should_serve_m2(tmp_path, "unknown_crop")
        assert ok is True and v["serve_m2"] is True

    def test_blocks_when_metrics_bad(self, tmp_path):
        arts = _write_meta(tmp_path, "melon", stage2_meta={"mape": 63.9, "cv_r2_mean": 0.5, "n_train": 42})
        ok, v = should_serve_m2(arts, "melon")
        assert ok is False and v["verdict"] == "fallback"


class TestCheckConsistency:
    def test_detects_divergence(self, tmp_path):
        _write_meta(
            tmp_path, "melon",
            stage2_meta={"mape": 63.9},
            pipeline_meta={"stage2": {"mape": 8.7}},
        )
        r = check_consistency(tmp_path, "melon")
        assert r["authoritative"] == 63.9
        assert "pipeline_meta" in r["diverged"]

    def test_no_divergence_when_aligned(self, tmp_path):
        _write_meta(
            tmp_path, "cucumber",
            stage2_meta={"mape": 22.8},
            pipeline_meta={"stage2": {"mape": 22.8}},
        )
        assert check_consistency(tmp_path, "cucumber")["diverged"] == {}
