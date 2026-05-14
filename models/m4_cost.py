"""M4 Cost — 고정비 + 변동비 분리 비용 모델.

비용 구조:
  고정비  = 종자·농약·감가상각·기타 (월할 배분, 면적 비례)
  변동비1 = 난방비 (내외부 온도차 × 계절 가중치 × 면적)
  변동비2 = 수확 인건비 (yield_kg_m2 × 단가/kg)
  변동비3 = 포장재비 (yield_kg_m2 × 단가/kg)
  변동비4 = 비료·양액비 (월정액, 면적 비례)

소득 = Stage3 매출 - total_cost_per_m2
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR   = Path(__file__).parent.parent / "api" / "data"
_COST_FILE  = _DATA_DIR / "cost_seasonal.json"
_SURVEY_FILE = _DATA_DIR / "income_survey.json"


@dataclass
class CostBreakdown:
    fixed_per_m2: float          # 고정비 (종자·농약·감가 등)
    heating_per_m2: float        # 난방비
    harvest_labor_per_m2: float  # 수확 인건비
    packaging_per_m2: float      # 포장재비
    fertilizer_per_m2: float     # 비료·양액비
    total_per_m2: float          # 합계


class M4CostModel:
    """작목별 월별 비용 추정 모델.

    cost_seasonal.json 파라미터 기반.
    모든 단위: 원/m²/월.
    """

    def __init__(self):
        self._params: dict[str, dict] = {}
        self._loaded = False

    def load(self) -> "M4CostModel":
        """비용 파라미터 파일 로드."""
        if _COST_FILE.exists():
            self._params = json.loads(_COST_FILE.read_text(encoding="utf-8"))
            logger.info("[M4Cost] cost_seasonal.json 로드 완료 (%d작목)", len(self._params))
        else:
            logger.warning("[M4Cost] cost_seasonal.json 없음 — income_survey.json 폴백")
            self._load_survey_fallback()
        self._loaded = True
        return self

    def _load_survey_fallback(self) -> None:
        """income_survey.json 기반 간략 폴백."""
        if not _SURVEY_FILE.exists():
            return
        survey = json.loads(_SURVEY_FILE.read_text(encoding="utf-8"))
        for crop_ko, d in survey.items():
            costs = d.get("cost_per_m2", {})
            total = sum(costs.values())
            season_months = 5.0  # 딸기 기준 5개월 작기
            self._params[crop_ko] = {
                "fixed_monthly_per_m2": round(total / season_months, 1),
                "heating_coef_per_degC_per_m2": 8.0,
                "heating_seasonal_multiplier": 1.5,
                "heating_months": [11, 12, 1, 2, 3],
                "harvest_labor_rate_per_kg": 180.0,
                "packaging_rate_per_kg": 45.0,
                "fertilizer_monthly_per_m2": 25.0,
            }

    def _get_params(self, crop_ko: str) -> dict:
        if not self._loaded:
            self.load()
        # 한글 키 → 없으면 딸기 기본값
        p = self._params.get(crop_ko) or self._params.get("딸기", {})
        if not p:
            logger.warning("[M4Cost] %s 파라미터 없음 — 하드코딩 기본값 사용", crop_ko)
            p = {
                "fixed_monthly_per_m2": 160.0,
                "heating_coef_per_degC_per_m2": 8.0,
                "heating_seasonal_multiplier": 1.5,
                "heating_months": [11, 12, 1, 2, 3],
                "harvest_labor_rate_per_kg": 180.0,
                "packaging_rate_per_kg": 45.0,
                "fertilizer_monthly_per_m2": 25.0,
            }
        return p

    def predict(
        self,
        month: int,
        temp_internal: float,
        temp_external: float,
        yield_kg_m2: float,
        crop_ko: str,
    ) -> CostBreakdown:
        """월별 비용/m² 계산.

        Args:
            month: 1~12
            temp_internal: 내부 온도 (°C)
            temp_external: 외부 온도 (°C)
            yield_kg_m2:   당월 수확량 (kg/m²)
            crop_ko:       작목명 (한국어)

        Returns:
            CostBreakdown
        """
        p = self._get_params(crop_ko)

        # ① 고정비
        fixed = float(p.get("fixed_monthly_per_m2", 160.0))

        # ② 난방비
        temp_diff = max(0.0, temp_internal - temp_external)
        coef = float(p.get("heating_coef_per_degC_per_m2", 8.0))
        heating_months = p.get("heating_months", [11, 12, 1, 2, 3])
        seasonal_w = float(p.get("heating_seasonal_multiplier", 1.5)) \
            if month in heating_months else 1.0
        heating = temp_diff * coef * seasonal_w

        # ③ 수확 인건비
        labor_rate = float(p.get("harvest_labor_rate_per_kg", 180.0))
        harvest_labor = max(0.0, yield_kg_m2) * labor_rate

        # ④ 포장재비
        pkg_rate = float(p.get("packaging_rate_per_kg", 45.0))
        packaging = max(0.0, yield_kg_m2) * pkg_rate

        # ⑤ 비료·양액비
        fertilizer = float(p.get("fertilizer_monthly_per_m2", 25.0))

        total = fixed + heating + harvest_labor + packaging + fertilizer

        return CostBreakdown(
            fixed_per_m2=round(fixed, 2),
            heating_per_m2=round(heating, 2),
            harvest_labor_per_m2=round(harvest_labor, 2),
            packaging_per_m2=round(packaging, 2),
            fertilizer_per_m2=round(fertilizer, 2),
            total_per_m2=round(total, 2),
        )

    def annual_cost_per_m2(self, crop_ko: str,
                           avg_yield_kg_m2_per_month: float = 0.5,
                           avg_temp_diff: float = 8.0) -> float:
        """연간 평균 비용/m² 추정 (12개월 합산)."""
        total = 0.0
        for m in range(1, 13):
            cb = self.predict(
                month=m,
                temp_internal=20.0,
                temp_external=20.0 - avg_temp_diff,
                yield_kg_m2=avg_yield_kg_m2_per_month,
                crop_ko=crop_ko,
            )
            total += cb.total_per_m2
        return round(total, 0)


# 모듈 레벨 싱글턴
_default_model: Optional[M4CostModel] = None


def get_cost_model() -> M4CostModel:
    global _default_model
    if _default_model is None:
        _default_model = M4CostModel().load()
    return _default_model
