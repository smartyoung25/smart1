"""Stage 4: 비용 파라미터 추출 스크립트.

cost_params.json + income_survey.json 데이터를 기반으로
작목별 비용 계수를 검증하고 cost_seasonal.json을 갱신한다.

실행:
  python scripts/train_stage4_cost.py
  python scripts/train_stage4_cost.py --crop 딸기
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "api" / "data"
COST_FILE = DATA_DIR / "cost_seasonal.json"

CROPS = ["딸기", "방울토마토", "완숙토마토", "참외", "파프리카"]

# 작목별 면적 기본값 (farm_registry median 기준)
AREA_DEFAULTS = {
    "딸기":       1200.0,
    "방울토마토": 1600.0,
    "완숙토마토": 1400.0,
    "참외":       3800.0,
    "파프리카":   2500.0,
}


def load_cost_params() -> dict:
    p = DATA_DIR / "cost_params.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    logger.warning("cost_params.json 없음")
    return {}


def load_farm_registry() -> dict:
    p = DATA_DIR / "farm_registry.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def compute_area_median(registry: dict, crop_ko: str) -> float:
    """farm_registry에서 작목별 면적 중앙값 계산."""
    # farm_registry.json 구조: {"farms": {"farm_id": {...}}, ...}
    farms_dict = registry.get("farms", registry)
    farms = [
        f for f in farms_dict.values()
        if isinstance(f, dict) and f.get("crop") == crop_ko
        and f.get("plant_area_m2", f.get("total_area_m2", f.get("area_m2", 0))) > 0
    ]
    if not farms:
        return AREA_DEFAULTS.get(crop_ko, 1200.0)
    areas = sorted(
        f.get("plant_area_m2", f.get("total_area_m2", f.get("area_m2", 0)))
        for f in farms
    )
    n = len(areas)
    median = areas[n // 2] if n % 2 == 1 else (areas[n // 2 - 1] + areas[n // 2]) / 2
    logger.info("  %s: 면적 중앙값 %.0fm² (n=%d농가)", crop_ko, median, n)
    return round(median, 0)


def derive_heating_coef(cost_params: dict, area_m2: float) -> float:
    """전기비 → 난방계수 추정.

    heating_coef = electricity_median_monthly / area_m2 / avg_delta_T
    avg_delta_T = 9°C (겨울철 내외부 온도차 가정)
    """
    elec = cost_params.get("monthly_costs_by_category", {}) \
                      .get("electricity", {}) \
                      .get("median_monthly_krw", 98500.0)
    delta_t_avg = 9.0
    coef = elec / area_m2 / delta_t_avg
    return round(coef, 2)


def derive_labor_rate(cost_params: dict) -> float:
    """인건비 kg당 단가 추정.

    labor_daily_median / avg_harvest_per_day
    딸기 기준 약 300 kg/일·인
    """
    daily = cost_params.get("labor_daily_rate", {}).get("median_daily_krw", 55000.0)
    kg_per_day = 300.0   # 일반 수확 작업 300kg/일
    return round(daily / kg_per_day, 1)


def validate_cost_ratio(crop_ko: str, params: dict) -> bool:
    """비용/매출 비율 현실성 검사 (배포 게이트 STAGE4_COST_VALID).

    비용합 / 추정매출 ≤ 50%
    딸기 추정매출: 5000원/m²/월 (price_stats.json 딸기 중앙값 × yield 중앙값)
    """
    revenue_estimates = {
        "딸기": 5000.0, "방울토마토": 3500.0, "완숙토마토": 2500.0,
        "참외": 4000.0, "파프리카": 6000.0,
    }
    est_rev = revenue_estimates.get(crop_ko, 4000.0)

    avg_yield = 0.5   # kg/m²/월 추정
    fixed = params["fixed_monthly_per_m2"]
    labor = avg_yield * params["harvest_labor_rate_per_kg"]
    pkg   = avg_yield * params["packaging_rate_per_kg"]
    fert  = params["fertilizer_monthly_per_m2"]
    heat  = 8.0 * params["heating_coef_per_degC_per_m2"]  # ΔT=8°C 가정

    total = fixed + labor + pkg + fert + heat
    ratio = total / est_rev
    passed = ratio <= 0.5
    logger.info("  비용/매출 검사: %.0f / %.0f = %.1f%%  %s",
                total, est_rev, ratio * 100, "✅ PASS" if passed else "❌ FAIL")
    return passed


def main(target_crops: list[str] | None = None):
    crops = target_crops or CROPS
    logger.info("Stage 4 비용 파라미터 검증 시작 (대상: %s)", crops)

    cost_params  = load_cost_params()
    registry     = load_farm_registry()

    # 기존 cost_seasonal.json 로드
    if COST_FILE.exists():
        seasonal = json.loads(COST_FILE.read_text(encoding="utf-8"))
    else:
        seasonal = {}

    for crop_ko in crops:
        logger.info("\n[%s]", crop_ko)

        area_m2 = compute_area_median(registry, crop_ko)
        heating_coef = derive_heating_coef(cost_params, area_m2) \
            if cost_params else seasonal.get(crop_ko, {}).get("heating_coef_per_degC_per_m2", 8.0)
        labor_rate = derive_labor_rate(cost_params) \
            if cost_params else seasonal.get(crop_ko, {}).get("harvest_labor_rate_per_kg", 180.0)

        # 현재 파라미터에 계산값으로 업데이트
        if crop_ko in seasonal:
            seasonal[crop_ko]["heating_coef_per_degC_per_m2"] = heating_coef
            seasonal[crop_ko]["harvest_labor_rate_per_kg"] = labor_rate
            logger.info("  난방계수 업데이트: %.2f 원/m²/°C", heating_coef)
            logger.info("  인건비 업데이트:   %.1f 원/kg", labor_rate)

            # 현실성 검사
            validate_cost_ratio(crop_ko, seasonal[crop_ko])
        else:
            logger.warning("  %s: cost_seasonal.json에 항목 없음 — 스킵", crop_ko)

    # 저장
    COST_FILE.write_text(
        json.dumps(seasonal, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("\n✅ cost_seasonal.json 저장 완료: %s", COST_FILE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop", nargs="*", default=None, help="대상 작목 (미지정 시 전체)")
    args = parser.parse_args()
    main(args.crop)
