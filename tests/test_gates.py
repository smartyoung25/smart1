"""게이트 단일 정책(pipeline/gates.py) 회귀 테스트.

배경: MAPE가 4곳(stage2_meta[권위]·pipeline_meta·registry·pkl 내부)에 기록되고
값이 조용히 어긋나 게이트·블렌딩·보고서가 동시에 틀어진 사고가 있었음.
이 테스트는 (1) 판정 규칙 (2) 권위 로딩 (3) fail-open (4) 괴리 감지를 고정한다.
"""
from __future__ import annotations

import json

import pytest

from pipeline.gates import (
    CV_R2_MIN, CV_R2_FALLBACK, MAPE_ADVISORY, N_MIN,
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
    """판정은 CV R² 중심 — MAPE 는 참고(경보)일 뿐 판정하지 않는다.

    ★ 이 규칙의 배경(2026-07-17): stage2_meta 의 `mape` 는 학습(in-sample) MAPE 였고
      게이트가 그 값으로 판정했다(딸기 학습 17.8% vs CV 107.3%). 또 monthly 는 수확
      초·말기 0 근처 표본 때문에 MAPE 가 구조적으로 폭발한다. 그래서 MAPE 를 판정에서
      내렸다. 아래 테스트가 그 정책을 고정한다.
    """

    def test_serve_when_cv_r2_ok(self):
        """딸기 실측: CV MAPE 107.3% 로 크지만 CV R² 0.295 → 검증 적용."""
        r = evaluate_m2_gate(107.3, 0.295, 6427)
        assert r["verdict"] == "serve" and r["serve_m2"] is True

    def test_mape_does_not_decide(self):
        """MAPE 가 아무리 커도 CV R² 가 충분하면 서빙 — 경보 플래그만 남는다."""
        r = evaluate_m2_gate(500.0, 0.40, 200)
        assert r["verdict"] == "serve"
        assert any("CV MAPE" in f for f in r["flags"])

    def test_fallback_when_cv_r2_negative(self):
        """방울토마토 실측: CV R² -0.257 → 평균 예측보다 나쁨 → 폴백."""
        r = evaluate_m2_gate(194.5, -0.257, 103)
        assert r["verdict"] == "fallback" and r["serve_m2"] is False

    def test_conditional_when_r2_too_low(self):
        """완숙토마토 실측: CV R² 0.099 → 설명력 부족 → 조건부(서빙은 유지)."""
        r = evaluate_m2_gate(85.4, 0.099, 177)
        assert r["verdict"] == "conditional" and r["serve_m2"] is True
        assert any("R²" in x for x in r["reasons"])

    def test_overfit_gap_forces_conditional(self):
        r = evaluate_m2_gate(10.0, 0.30, 500, train_r2=0.95)
        assert r["verdict"] == "conditional"

    def test_small_sample_flagged_but_verdict_kept(self):
        """오이 실측: n=61 이지만 CV R² 0.386 → 서빙. 소표본은 플래그만."""
        r = evaluate_m2_gate(50.0, 0.386, 30)
        assert r["verdict"] == "serve"
        assert any("소표본" in f for f in r["flags"])

    def test_none_cv_r2_is_fallback(self):
        """검증 지표가 없으면 판정 불가 → 폴백. 학습값으로 대신 판정하지 않는다."""
        assert evaluate_m2_gate(10.0, None)["serve_m2"] is False
        assert evaluate_m2_gate(None, None)["serve_m2"] is False

    def test_boundaries(self):
        assert evaluate_m2_gate(10.0, CV_R2_MIN, 100)["verdict"] == "serve"
        assert evaluate_m2_gate(10.0, CV_R2_MIN - 0.01, 100)["verdict"] == "conditional"
        assert evaluate_m2_gate(10.0, CV_R2_FALLBACK + 0.01, 100)["verdict"] == "conditional"
        assert evaluate_m2_gate(10.0, CV_R2_FALLBACK, 100)["verdict"] == "fallback"

    def test_passes_gate_alias(self):
        assert passes_gate(107.3, 0.3, 100) is True
        assert passes_gate(50.0, -0.1, 100) is False


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
        """권위(stage2_meta)의 CV R² 로 판정 — pipeline_meta 의 낙관값에 속지 않는다."""
        arts = _write_meta(
            tmp_path, "melon",
            stage2_meta={"cv_mape_mean": 56.8, "cv_r2_mean": -0.059, "n_train": 84},
            pipeline_meta={"stage2": {"cv_r2_mean": 0.8, "cv_mape_mean": 8.7}},
        )
        assert evaluate_crop(arts, "melon")["verdict"] == "fallback"

    def test_training_mape_never_decides(self, tmp_path):
        """★ 사고 재발 방지: stage2_meta 에 낙관적 학습 mape 만 있어도 판정에 쓰지 않는다.
        cv_r2_mean 이 없으면 '판정 불가 → 폴백' 이어야 한다(구 게이트는 serve 였다)."""
        arts = _write_meta(tmp_path, "strawberry", stage2_meta={"mape": 17.8, "n_train": 6427})
        assert evaluate_crop(arts, "strawberry")["verdict"] == "fallback"

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
        """CV R² 가 0 이하면 서빙 차단 — 평균 예측보다 나쁜 모델."""
        arts = _write_meta(tmp_path, "melon",
                           stage2_meta={"cv_mape_mean": 56.8, "cv_r2_mean": -0.059, "n_train": 84})
        ok, v = should_serve_m2(arts, "melon")
        assert ok is False and v["verdict"] == "fallback"

    def test_fail_open_when_only_training_mape(self, tmp_path):
        """구 아티팩트(학습 mape 만 있음) → 판정 불가 → fail-open 으로 서빙 유지.
        재학습으로 CV 지표를 채운 뒤 판정한다(서빙 중단은 별도 결정)."""
        arts = _write_meta(tmp_path, "old", stage2_meta={"mape": 17.8, "n_train": 100})
        ok, v = should_serve_m2(arts, "old")
        assert ok is True and "CV R²" in v["reasons"][0]


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
