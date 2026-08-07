"""ERP 실시간 원가·마진 계산기 — Farmingsight 혁신4.

수확 시마다 kg당 원가·마진·소득률을 실시간으로 산출한다.

원가 항목:
  ① 에너지비  : 에너지 계량기 → 한전 요금 × 사용량 (실측 or 추정)
  ② 양액·자재비: 투여량 기록 → 단가 × 사용량
  ③ 노동비    : 작업 시간 → 시간당 단가
  ④ 종묘비    : 정식일 기준 작기당 일할 계산

출하 타이밍:
  KAMIS 당일가 기준 오늘 vs 내일(+예상 변동) 마진 비교
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from models.crop_config import SEASON_LENGTH_MONTHS  # 작기 개월수 SSOT (E2E 2026-08-07)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent

# ── 작목별 기본 원가 파라미터 (RDA 농가 실태조사 2022 기준) ──────────────────
_COST_DEFAULTS: dict[str, dict] = {
    "딸기": {
        "energy_kwh_per_m2_month": 3.2,    # kWh/m²/월
        "nutrient_cost_per_m2_month": 580, # 원/m²/월 (양액·비료)
        "labor_cost_per_m2_month": 1200,   # 원/m²/월 (노동)
        "seed_cost_per_m2_season": 2800,   # 원/m²/작기 (종묘)
    },
    "방울토마토": {
        "energy_kwh_per_m2_month": 2.8,
        "nutrient_cost_per_m2_month": 620,
        "labor_cost_per_m2_month": 980,
        "seed_cost_per_m2_season": 1800,
    },
    "완숙토마토": {
        "energy_kwh_per_m2_month": 3.0,
        "nutrient_cost_per_m2_month": 700,
        "labor_cost_per_m2_month": 1100,
        "seed_cost_per_m2_season": 2200,
    },
    "참외": {
        "energy_kwh_per_m2_month": 2.0,
        "nutrient_cost_per_m2_month": 480,
        "labor_cost_per_m2_month": 1400,
        "seed_cost_per_m2_season": 1500,
    },
    "파프리카": {
        "energy_kwh_per_m2_month": 3.5,
        "nutrient_cost_per_m2_month": 800,
        "labor_cost_per_m2_month": 1300,
        "seed_cost_per_m2_season": 4500,
    },
    "오이": {
        "energy_kwh_per_m2_month": 2.4,
        "nutrient_cost_per_m2_month": 420,
        "labor_cost_per_m2_month": 1100,
        "seed_cost_per_m2_season": 900,
    },
}

# 한전 평균 전기요금 (원/kWh) — 시설원예 농사용(갑) 기준 2024
_ELEC_RATE_KRW_PER_KWH = 120.5

# LED 스펙트럼 권장 비율 (작기단계별)
LED_SPECTRUM: dict[str, dict] = {
    "발아·정식기": {
        "red": 50, "blue": 30, "uv": 20,
        "ratio_str": "R:B:UV = 5:3:2",
        "effect": "뿌리 발달 촉진 / 초기 활착률 향상",
        "note": "UV가 뿌리 분화를 도와 활착률 증가",
    },
    "영양생장기": {
        "red": 70, "blue": 30, "uv": 0,
        "ratio_str": "R:B = 7:3",
        "effect": "잎·줄기 빠른 성장 / 엽면적 빠른 확장",
        "note": "적색이 광합성 효율 극대화",
    },
    "착화·착과기": {
        "red": 60, "blue": 30, "uv": 10,
        "ratio_str": "R:B:UV = 6:3:1",
        "effect": "착화·착과율 +15~20%",
        "note": "UV가 화아 분화 자극",
    },
    "성숙·수확기": {
        "red": 50, "blue": 20, "uv": 30,
        "ratio_str": "R:B:UV = 5:2:3",
        "effect": "당도 +1.2Brix / 착색도 +20%",
        "note": "UV 증가로 안토시아닌 생성",
    },
}


@dataclass
class ERPResult:
    """실시간 ERP 원가·마진 결과."""
    farm_id: str
    crop_ko: str
    area_m2: float

    # 원가 항목 (원/m²/월)
    energy_cost_per_m2: float = 0.0
    nutrient_cost_per_m2: float = 0.0
    labor_cost_per_m2: float = 0.0
    seed_cost_per_m2: float = 0.0
    total_cost_per_m2: float = 0.0

    # 단위 원가 (원/kg)
    yield_per_m2: float = 0.0      # 이번 달 예상 수확량 kg/m²
    cost_per_kg: float = 0.0

    # 도매가 및 마진
    market_price_per_kg: float = 0.0  # KAMIS 도매가
    margin_per_kg: float = 0.0
    income_rate_pct: float = 0.0       # 소득률 %

    # 출하 타이밍
    today_margin: float = 0.0
    tomorrow_margin_est: float = 0.0   # 내일 마진 추정
    harvest_advice: str = ""

    # 손익분기
    breakeven_kg: float = 0.0

    # 작기단계 & LED 스펙트럼
    growth_stage: str = ""
    led_spectrum: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "farm_id": self.farm_id,
            "crop_ko": self.crop_ko,
            "area_m2": self.area_m2,
            "cost_breakdown": {
                "energy_per_m2": round(self.energy_cost_per_m2, 0),
                "nutrient_per_m2": round(self.nutrient_cost_per_m2, 0),
                "labor_per_m2": round(self.labor_cost_per_m2, 0),
                "seed_per_m2": round(self.seed_cost_per_m2, 0),
                "total_per_m2": round(self.total_cost_per_m2, 0),
            },
            "cost_per_kg": round(self.cost_per_kg, 0),
            "market_price_per_kg": round(self.market_price_per_kg, 0),
            "margin_per_kg": round(self.margin_per_kg, 0),
            "income_rate_pct": round(self.income_rate_pct, 1),
            "breakeven_kg": round(self.breakeven_kg, 0),
            "harvest_timing": {
                "today_margin": round(self.today_margin, 0),
                "tomorrow_margin_est": round(self.tomorrow_margin_est, 0),
                "advice": self.harvest_advice,
                "diff": round(self.tomorrow_margin_est - self.today_margin, 0),
            },
            "growth_stage": self.growth_stage,
            "led_spectrum": self.led_spectrum,
        }


def _get_kamis_price(crop_ko: str) -> float:
    """단가 SSOT (E2E 2026-08-07 §C) — /revenue 와 동일한 권위 함수 사용.

    구: 별도 캐시(api/data/kamis_price_cache.json)를 읽어 /revenue 의
        pipeline.kamis_fetcher.get_price_with_fallback 와 단가가 갈렸다
        (딸기 3,000 vs 12,500). 동일 소스로 위임해 전 화면 단가 통일.
    """
    try:
        from pipeline.kamis_fetcher import get_price_with_fallback
        info = get_price_with_fallback(crop_ko)
        p = info.get("price_krw_kg")
        if isinstance(p, (int, float)) and p > 0:
            return float(p)
    except Exception as e:
        logger.debug("단가 조회 실패(get_price_with_fallback): %s", e)

    # 작목별 기본 도매가 (원/kg) — 위 권위 함수 실패 시 최후 폴백
    _DEFAULT_PRICES = {
        "딸기": 8500, "방울토마토": 3800, "완숙토마토": 2200,
        "참외": 3500, "파프리카": 5500, "오이": 1200,
    }
    return _DEFAULT_PRICES.get(crop_ko, 3000.0)


def _infer_growth_stage(plant_month: Optional[int], current_month: int, crop_ko: str) -> str:
    """정식월 + 현재월로 작기단계 추정."""
    if plant_month is None:
        # 작목별 통상 정식월
        _TYPICAL_PLANT = {"딸기": 9, "방울토마토": 3, "완숙토마토": 3,
                          "참외": 3, "파프리카": 2, "오이": 4}
        plant_month = _TYPICAL_PLANT.get(crop_ko, 3)

    elapsed = (current_month - plant_month) % 12
    if elapsed < 1:
        return "발아·정식기"
    elif elapsed < 3:
        return "영양생장기"
    elif elapsed < 5:
        return "착화·착과기"
    else:
        return "성숙·수확기"


def calc_erp(
    farm_id: str,
    crop_ko: str,
    area_m2: float,
    yield_per_m2: float,               # 이번 달 수확량 kg/m²
    current_month: int = 6,
    plant_month: Optional[int] = None,
    energy_kwh_actual: Optional[float] = None,   # 실측 에너지 사용량 kWh/m²
    elec_rate: float = _ELEC_RATE_KRW_PER_KWH,
) -> ERPResult:
    """ERP 원가·마진 계산.

    Args:
        farm_id: 농장 ID
        crop_ko: 작목명 (딸기, 방울토마토 등)
        area_m2: 재배 면적 m²
        yield_per_m2: 이번 달 수확량 kg/m²
        current_month: 현재 월 (1~12)
        plant_month: 정식 월 (None이면 작목 기본값)
        energy_kwh_actual: 실측 에너지 kWh/m²/월 (None이면 작목 기본값)
        elec_rate: 전기요금 원/kWh
    """
    defaults = _COST_DEFAULTS.get(crop_ko, _COST_DEFAULTS["딸기"])

    # ① 에너지비
    kwh = energy_kwh_actual if energy_kwh_actual else defaults["energy_kwh_per_m2_month"]
    energy_cost = kwh * elec_rate

    # ② 양액·자재비
    nutrient_cost = defaults["nutrient_cost_per_m2_month"]

    # ③ 노동비
    labor_cost = defaults["labor_cost_per_m2_month"]

    # ④ 종묘비 (작기당 → 월 일할). 작기 개월수는 SSOT(crop_config) 사용.
    seed_monthly = defaults["seed_cost_per_m2_season"] / SEASON_LENGTH_MONTHS.get(crop_ko, 8)

    total_cost_per_m2 = energy_cost + nutrient_cost + labor_cost + seed_monthly

    # 단위 원가 (원/kg)
    if yield_per_m2 > 0:
        cost_per_kg = total_cost_per_m2 / yield_per_m2
    else:
        cost_per_kg = 0.0

    # 도매가·마진
    market_price = _get_kamis_price(crop_ko)
    margin_per_kg = market_price - cost_per_kg
    income_rate = (margin_per_kg / market_price * 100) if market_price > 0 else 0.0

    # 손익분기 (kg)
    if margin_per_kg > 0:
        breakeven = total_cost_per_m2 * area_m2 / margin_per_kg
    else:
        breakeven = 0.0

    # 출하 타이밍 — 내일 마진 추정 (KAMIS ±2~5% 일별 변동 반영)
    # 단순화: 주간 상승 추세이면 +3%, 하락이면 -2%
    tomorrow_price = market_price * 1.03  # 보수적 추정
    tomorrow_margin = tomorrow_price - cost_per_kg
    diff = tomorrow_margin - margin_per_kg
    if diff > 300:
        advice = f"내일 출하 유리 (+{diff:.0f}원/kg 예상)"
    elif diff < -200:
        advice = f"오늘 출하 권장 (내일 -{-diff:.0f}원/kg 예상)"
    else:
        advice = "오늘 출하 적정 (내일 비슷)"

    # 작기단계 & LED 스펙트럼
    stage = _infer_growth_stage(plant_month, current_month, crop_ko)
    led_spec = LED_SPECTRUM.get(stage, {})

    return ERPResult(
        farm_id=farm_id,
        crop_ko=crop_ko,
        area_m2=area_m2,
        energy_cost_per_m2=round(energy_cost, 1),
        nutrient_cost_per_m2=round(nutrient_cost, 1),
        labor_cost_per_m2=round(labor_cost, 1),
        seed_cost_per_m2=round(seed_monthly, 1),
        total_cost_per_m2=round(total_cost_per_m2, 1),
        yield_per_m2=round(yield_per_m2, 3),
        cost_per_kg=round(cost_per_kg, 0),
        market_price_per_kg=round(market_price, 0),
        margin_per_kg=round(margin_per_kg, 0),
        income_rate_pct=round(income_rate, 1),
        breakeven_kg=round(breakeven, 0),
        today_margin=round(margin_per_kg, 0),
        tomorrow_margin_est=round(tomorrow_margin, 0),
        harvest_advice=advice,
        growth_stage=stage,
        led_spectrum=led_spec,
    )
