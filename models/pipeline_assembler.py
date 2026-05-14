"""FourStagePipeline — 4-Stage 분리 학습 모델 조립 클래스.

순서:
  Stage 1 (M1): 환경[t-lag] → 생육[t]
  Stage 2 (M2): 생육[t] + 환경[t] → yield_per_m2[t+1]
  Stage 3 (M3): yield × price → revenue_per_m2
  Stage 4 (비용): 환경 + 수확량 → cost_per_m2

  소득/m² = revenue_per_m2 - cost_per_m2
"""
from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class IncomeResult:
    yield_kg_m2: float        # 예측 수확량 (kg/m²)
    revenue_per_m2: float     # 예측 매출 (원/m²)
    cost_per_m2: float        # 예측 비용 (원/m²)
    income_per_m2: float      # 소득 (원/m²)
    total_income: float       # 총 소득 = income_per_m2 × area_m2
    lower_80: float           # 매출 하한 (80% 구간)
    upper_80: float           # 매출 상한
    confidence: float         # 0~1
    cost_breakdown: dict      # 비용 세부


class FourStagePipeline:
    """작목별 4단계 파이프라인 조립 및 예측."""

    def __init__(self, crop_ko: str):
        from models.crop_config import CROP_CONFIGS, get_artifact_dir
        self.crop_ko = crop_ko
        self.config  = CROP_CONFIGS.get(crop_ko)
        if not self.config:
            raise ValueError(f"지원하지 않는 작목: {crop_ko}")

        art_dir = get_artifact_dir(self.config.crop_en)
        self._art_dir = art_dir

        # Stage 1: 생육 예측 모델
        self._s1 = self._load_pkl(art_dir / "stage1_growth.pkl")
        # Stage 2: 수확량 예측 모델
        self._s2 = self._load_pkl(art_dir / "stage2_yield.pkl")
        # Stage 3: 매출 모델
        from models.m3_revenue import M3RevenueModel
        self._s3 = M3RevenueModel().load(art_dir / "stage3_revenue_coef.pkl")
        # Stage 4: 비용 모델
        from models.m4_cost import M4CostModel
        self._s4 = M4CostModel().load()

        logger.info("[FourStage] %s 로드 완료 (S1=%s S2=%s)",
                    crop_ko,
                    "✓" if self._s1 else "✗",
                    "✓" if self._s2 else "✗")

    @staticmethod
    def _load_pkl(path: Path) -> Optional[dict]:
        if path.exists():
            with open(path, "rb") as f:
                return pickle.load(f)
        logger.warning("[FourStage] pkl 없음: %s", path)
        return None

    # ── Stage 1: 생육 예측 ────────────────────────────────────────────────────

    def predict_growth(
        self,
        env_current: dict,
        env_lag1: Optional[dict] = None,
        env_lag2: Optional[dict] = None,
    ) -> dict:
        """환경 → 생육 예측. 결과: {growth_초장: ..., growth_엽수: ...}"""
        if self._s1 is None:
            return {}

        bundle = self._s1
        feat_cols = bundle.get("feature_cols", [])
        imputer   = bundle.get("imputer")
        model     = bundle.get("model")

        # 피처 행 구성
        row = {}
        for col in feat_cols:
            if col.endswith("_lag1") and env_lag1:
                base = col[:-5]
                row[col] = env_lag1.get(base, np.nan)
            elif col.endswith("_lag2") and env_lag2:
                base = col[:-5]
                row[col] = env_lag2.get(base, np.nan)
            elif col == "gdd_monthly":
                t = env_current.get("temp_internal", 20.0)
                row[col] = max(0.0, t - self.config.t_base) * 30
            elif col == "month_sin":
                row[col] = 0.0  # 호출자가 month 정보 없으면 0
            elif col == "month_cos":
                row[col] = 1.0
            else:
                row[col] = env_current.get(col, np.nan)

        X_raw = np.array([[row.get(c, np.nan) for c in feat_cols]])
        if imputer:
            X = imputer.transform(X_raw)
        else:
            X = X_raw

        if "scaler" in bundle:
            X = bundle["scaler"].transform(X)

        target_cols = bundle.get("target_cols", [])
        try:
            y_pred = model.predict(X)[0]
        except Exception as e:
            logger.warning("[FourStage.S1] 예측 실패: %s", e)
            return {}

        return {tc: float(y_pred[i]) for i, tc in enumerate(target_cols)}

    # ── Stage 2: 수확량 예측 ──────────────────────────────────────────────────

    def predict_yield(
        self,
        growth: dict,
        env_current: dict,
        month: int,
    ) -> float:
        """생육 + 환경 → yield_per_m2 (kg/m²)."""
        if self._s2 is None:
            return 0.0

        bundle   = self._s2
        feat_cols = bundle.get("feature_cols", [])
        imputer   = bundle.get("imputer")
        model     = bundle.get("model")
        log_tf    = bundle.get("log_transform", True)

        row = {}
        for col in feat_cols:
            if col in growth:
                row[col] = growth[col]
            elif col in env_current:
                row[col] = env_current[col]
            elif col == "gdd_monthly":
                t = env_current.get("temp_internal", 20.0)
                row[col] = max(0.0, t - self.config.t_base) * 30
            elif col == "month_sin":
                row[col] = np.sin(2 * np.pi * month / 12)
            elif col == "month_cos":
                row[col] = np.cos(2 * np.pi * month / 12)
            else:
                row[col] = np.nan

        X_raw = np.array([[row.get(c, np.nan) for c in feat_cols]])
        if imputer:
            X = imputer.transform(X_raw)
        else:
            X = X_raw

        if "scaler" in bundle:
            X = bundle["scaler"].transform(X)

        try:
            y_raw = model.predict(X)[0]
            return float(np.expm1(y_raw)) if log_tf else float(y_raw)
        except Exception as e:
            logger.warning("[FourStage.S2] 예측 실패: %s", e)
            return 0.0

    # ── 통합 예측 ─────────────────────────────────────────────────────────────

    def predict(
        self,
        env_current: dict,
        month: int,
        area_m2: float,
        env_lag1: Optional[dict] = None,
        env_lag2: Optional[dict] = None,
        growth_actual: Optional[dict] = None,
    ) -> IncomeResult:
        """4-Stage 순차 예측 → 소득 계산.

        Args:
            env_current:   현재 월 환경 {temp_internal, humidity_int, ...}
            month:         수확 예정 월 (1~12)
            area_m2:       재배 면적
            env_lag1:      1개월 전 환경 (없으면 current로 대체)
            env_lag2:      2개월 전 환경 (없으면 current로 대체)
            growth_actual: 실측 생육 {growth_초장: ...} (없으면 S1 예측)
        """
        lag1 = env_lag1 or env_current
        lag2 = env_lag2 or env_current

        # Stage 1: 생육
        growth = growth_actual or self.predict_growth(env_current, lag1, lag2)

        # Stage 2: 수확량
        yield_kg_m2 = self.predict_yield(growth, env_current, month)

        # Stage 3: 매출
        rev_result = self._s3.predict(yield_kg_m2, month, self.crop_ko)

        # Stage 4: 비용
        cost_cb = self._s4.predict(
            month=month,
            temp_internal=float(env_current.get("temp_internal", 20.0)),
            temp_external=float(env_current.get("temp_external", 5.0)),
            yield_kg_m2=yield_kg_m2,
            crop_ko=self.crop_ko,
        )

        income_per_m2 = rev_result.revenue_per_m2 - cost_cb.total_per_m2
        total_income  = income_per_m2 * area_m2

        return IncomeResult(
            yield_kg_m2=round(yield_kg_m2, 4),
            revenue_per_m2=rev_result.revenue_per_m2,
            cost_per_m2=cost_cb.total_per_m2,
            income_per_m2=round(income_per_m2, 2),
            total_income=round(total_income, 0),
            lower_80=rev_result.lower_80,
            upper_80=rev_result.upper_80,
            confidence=rev_result.confidence,
            cost_breakdown={
                "fixed":         cost_cb.fixed_per_m2,
                "heating":       cost_cb.heating_per_m2,
                "harvest_labor": cost_cb.harvest_labor_per_m2,
                "packaging":     cost_cb.packaging_per_m2,
                "fertilizer":    cost_cb.fertilizer_per_m2,
            },
        )

    # ── 환경 최적화 ───────────────────────────────────────────────────────────

    def optimize_env(
        self,
        month: int,
        area_m2: float,
        env_base: Optional[dict] = None,
        n_months: int = 6,
    ) -> list[dict]:
        """환경 파라미터 그리드 서치 → 소득 최대 조합 반환.

        profit_optimizer.py의 그리드 로직을 FourStagePipeline 기반으로 실행.
        """
        from itertools import product

        cfg = self.config
        temp_range  = np.arange(cfg.opt_temp_range[0],  cfg.opt_temp_range[1]  + 1, 1.0)
        humid_range = np.arange(cfg.opt_humid_range[0], cfg.opt_humid_range[1] + 1, 5.0)
        co2_range   = np.arange(cfg.opt_co2_range[0],   cfg.opt_co2_range[1]   + 1, 200.0)

        base = env_base or {
            "temp_internal": float(np.mean(cfg.opt_temp_range)),
            "humidity_int":  float(np.mean(cfg.opt_humid_range)),
            "co2_ppm":       float(np.mean(cfg.opt_co2_range)),
            "temp_external": 5.0,
        }

        results = []
        for temp, humid, co2 in product(temp_range, humid_range, co2_range):
            env_cand = {**base, "temp_internal": temp,
                        "humidity_int": humid, "co2_ppm": co2}
            monthly_income = 0.0
            for m_offset in range(n_months):
                cur_month = ((month - 1 + m_offset) % 12) + 1
                ir = self.predict(env_cand, cur_month, area_m2)
                monthly_income += ir.income_per_m2

            results.append({
                "temp": round(temp, 1),
                "humid": round(humid, 1),
                "co2": round(co2, 1),
                "income_total": round(monthly_income * area_m2, 0),
                "income_per_m2_avg": round(monthly_income / n_months, 2),
            })

        results.sort(key=lambda x: x["income_total"], reverse=True)
        return results[:5]


# ── 싱글턴 캐시 ───────────────────────────────────────────────────────────────
_pipelines: dict[str, FourStagePipeline] = {}


def get_pipeline(crop_ko: str) -> Optional[FourStagePipeline]:
    if crop_ko not in _pipelines:
        try:
            _pipelines[crop_ko] = FourStagePipeline(crop_ko)
        except Exception as e:
            logger.error("[FourStage] %s 로드 실패: %s", crop_ko, e)
            return None
    return _pipelines[crop_ko]
