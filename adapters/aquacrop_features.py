"""AquaCrop / FAO-56 기반 물리 피처 계산 모듈.

데이터 부족 문제를 보완하기 위해 50년 FAO 작물과학 연구를 피처로 변환.
ML 모델이 학습 데이터 없이도 알아야 할 물리적 패턴을 사전 주입.

참고문헌:
  Allen et al. (1998) FAO-56: Crop Evapotranspiration
  Steduto et al. (2009) AquaCrop — The FAO Crop Model
  Vanthoor et al. (2011) Greenhouse Crop Model (토마토)
  Marcelis et al. (1998) Modelling biomass production and yield of horticultural crops
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional


# ── 작목별 물리 상수 (FAO-56 / AquaCrop 기준) ───────────────────────────────

# GDD 전체 생육기간 (정식→수확 완료, °C·day)
# 스마트팜 환경에서 재배기간 × 평균 유효온도 근사
_GDD_FULL_CYCLE: dict[str, float] = {
    "strawberry":    2200.0,   # 10월 정식, 5월 수확 완료 (210일 × 10.5°C eff)
    "cherry_tomato": 1800.0,   # 12주 생육 후 착과 (180일 × 10°C eff)
    "tomato":        1800.0,   # 완숙토마토 유사
    "paprika":       2500.0,   # 파프리카: 장기 재배 (250일 × 10°C eff)
    "melon":         1200.0,   # 참외: 단기 집약 재배 (100일 × 12°C eff)
    "cucumber":      1000.0,   # 오이: 빠른 회전 (80일 × 12.5°C eff)
}

# DLI 광포화점 (mol/m²/day) — 이 이상 빛을 줘도 광합성 증가 없음
# 참고: Sager et al., 딸기 8-12, 토마토 25-30, 파프리카 18-22
_DLI_SATURATION: dict[str, float] = {
    "strawberry":    10.0,
    "cherry_tomato": 22.0,
    "tomato":        22.0,
    "paprika":       20.0,
    "melon":         18.0,
    "cucumber":      18.0,
}

# VPD 최적 범위 (kPa) — 이 범위를 벗어나면 기공 폐쇄·낙화 스트레스
_VPD_OPT_RANGE: dict[str, tuple[float, float]] = {
    "strawberry":    (0.5, 1.0),
    "cherry_tomato": (0.8, 1.4),
    "tomato":        (0.8, 1.4),
    "paprika":       (0.7, 1.3),
    "melon":         (0.8, 1.5),
    "cucumber":      (0.7, 1.3),
}

# 작목별 Kc_mid (최성기 작물계수, FAO-56 Table 12 기반)
_KC_MID: dict[str, float] = {
    "strawberry":    0.85,
    "cherry_tomato": 1.15,
    "tomato":        1.20,
    "paprika":       1.10,
    "melon":         1.00,
    "cucumber":      1.00,
}


# ── 핵심 물리 피처 계산 함수 ──────────────────────────────────────────────────

def calc_cwsi(
    et_actual: pd.Series,
    et0: pd.Series,
    kc: float = 1.0,
) -> pd.Series:
    """CWSI — 작물수분스트레스지수 (Crop Water Stress Index).

    CWSI = 1 - ET_actual / ET_potential
    ET_potential = ET0 × Kc  (FAO-56 단일 Kc 방법)

    범위: 0 (스트레스 없음) ~ 1 (완전 스트레스)
    현장 의미: 0.3 이상이면 관수 필요 신호
    """
    et_pot = (et0 * kc).clip(lower=0.01)
    cwsi = (1.0 - et_actual / et_pot).clip(0.0, 1.0)
    return cwsi.fillna(0.0)


def calc_bai(
    dli_series: pd.Series,
    gdd_series: pd.Series,
    kc_mid: float = 1.0,
) -> pd.Series:
    """BAI — 바이오매스축적지수 (Biomass Accumulation Index).

    BAI = Σ(DLI × GDD_normalized × Kc_mid)
    AquaCrop의 biomass production = WP × ET_actual 에서 광 기반으로 단순화.

    높을수록 누적 광합성·생장량이 많음 — 수확량과 강한 상관관계.
    """
    # GDD를 0~1로 정규화 (월 단위이므로 최대 300°C·day로 나눔)
    gdd_norm = (gdd_series / 300.0).clip(0.0, 1.0).fillna(0.0)
    bai = (dli_series * gdd_norm * kc_mid).fillna(0.0)
    return bai.clip(lower=0.0)


def calc_phenology_stage(
    gdd_cumsum: pd.Series,
    gdd_full_cycle: float,
) -> pd.Series:
    """페놀로지 단계 (Phenology Stage, 0~1).

    GDD_cumsum / GDD_full_cycle
    0: 정식 직후 (영양생장 초기)
    0.3~0.5: 개화·착과기
    0.7~1.0: 수확기·생육 후기

    모델이 생육 단계를 알면 단계별 환경 반응 차이를 학습 가능.
    """
    stage = (gdd_cumsum / gdd_full_cycle).clip(0.0, 1.2)
    return stage.fillna(0.0)


def calc_vpd_stress_cum(
    vpd_series: pd.Series,
    vpd_opt_range: tuple[float, float],
) -> pd.Series:
    """VPD 스트레스 누적량 (kPa 초과분, 월 단위).

    Σ max(0, VPD - VPD_upper) + Σ max(0, VPD_lower - VPD)
    낙화·기공 폐쇄 스트레스의 대리 변수.
    높을수록 수확량 감소 위험.
    """
    lo, hi = vpd_opt_range
    stress_high = (vpd_series - hi).clip(lower=0.0)
    stress_low  = (lo - vpd_series).clip(lower=0.0)
    total_stress = (stress_high + stress_low).fillna(0.0)
    return total_stress


def calc_light_saturation(
    dli_series: pd.Series,
    dli_saturation: float,
) -> pd.Series:
    """일사 포화도 (Light Saturation Ratio, 0~1).

    min(1, DLI / DLI_saturation)
    Liebig's law: 포화점 이상에서는 추가 빛의 효과 없음.
    딸기처럼 광포화점이 낮은 작목은 과조사 스트레스 감지 가능.
    """
    sat = (dli_series / dli_saturation).clip(0.0, 1.0)
    return sat.fillna(0.0)


# ── 통합 함수: build_stage1_matrix에서 한 번에 호출 ──────────────────────────

def add_aquacrop_features(
    df: pd.DataFrame,
    crop_en: str,
    gdd_cumsum_col: str = "gdd_cumsum",
    dli_col: str = "dli_est",
    vpd_col: str = "vpd_kpa",
    et0_col: Optional[str] = "et0_mm",
) -> pd.DataFrame:
    """AquaCrop 5종 물리 피처를 DataFrame에 추가.

    Args:
        df: build_stage1_matrix 내부의 피처 행렬
        crop_en: 작목 영문 식별자 (strawberry, cherry_tomato, ...)
        gdd_cumsum_col: 누적 GDD 컬럼명
        dli_col: DLI 추정값 컬럼명
        vpd_col: VPD 컬럼명
        et0_col: ET₀ 컬럼명 (없으면 DLI 기반 추정)

    Returns:
        물리 피처가 추가된 DataFrame
    """
    df = df.copy()

    gdd_full   = _GDD_FULL_CYCLE.get(crop_en, 1500.0)
    dli_sat    = _DLI_SATURATION.get(crop_en, 18.0)
    vpd_opt    = _VPD_OPT_RANGE.get(crop_en, (0.7, 1.3))
    kc_mid_val = _KC_MID.get(crop_en, 1.0)

    # 1) 페놀로지 단계
    if gdd_cumsum_col in df.columns:
        df["phenology_stage"] = calc_phenology_stage(
            df[gdd_cumsum_col], gdd_full
        )
        # 페놀로지 제곱 (개화·착과기 비선형 반응 포착)
        df["phenology_stage_sq"] = df["phenology_stage"] ** 2
    else:
        df["phenology_stage"] = 0.0
        df["phenology_stage_sq"] = 0.0

    # 2) 일사 포화도
    if dli_col in df.columns:
        df["light_saturation"] = calc_light_saturation(df[dli_col], dli_sat)
    else:
        df["light_saturation"] = 0.5

    # 3) VPD 스트레스 누적
    if vpd_col in df.columns:
        df["vpd_stress_cum"] = calc_vpd_stress_cum(df[vpd_col], vpd_opt)
    else:
        df["vpd_stress_cum"] = 0.0

    # 4) BAI (바이오매스축적지수)
    if dli_col in df.columns and gdd_cumsum_col in df.columns:
        _gdd_monthly = df[gdd_cumsum_col].diff().fillna(df[gdd_cumsum_col])
        df["bai"] = calc_bai(df[dli_col], _gdd_monthly, kc_mid_val)
        # BAI 누적 (월별 합산)
        if "farm_id" in df.columns:
            df["bai_cumsum"] = (
                df.sort_values(["farm_id", "year", "month"])
                .groupby("farm_id")["bai"]
                .transform(lambda s: s.cumsum())
            )
        else:
            df["bai_cumsum"] = df["bai"].cumsum()
    else:
        df["bai"] = 0.0
        df["bai_cumsum"] = 0.0

    # 5) CWSI (ET 데이터 있을 때만; 없으면 VPD 기반 근사)
    if et0_col and et0_col in df.columns:
        # ET_actual ≈ ET0 × Kc_mid (실측 ET 없으면 최적 가정)
        et_actual = df[et0_col] * kc_mid_val
        df["cwsi"] = calc_cwsi(et_actual, df[et0_col], kc_mid_val)
    elif vpd_col in df.columns:
        # VPD 기반 CWSI 근사: 높은 VPD → 기공 폐쇄 → 실제 ET 감소
        vpd_lo, vpd_hi = vpd_opt
        vpd_clamped = df[vpd_col].clip(lower=0.1)
        # 최적 VPD 중간값 기준 상대 ET 추정
        vpd_mid = (vpd_lo + vpd_hi) / 2.0
        et_ratio = (vpd_mid / vpd_clamped).clip(0.2, 1.0)
        df["cwsi"] = (1.0 - et_ratio).clip(0.0, 0.8)
    else:
        df["cwsi"] = 0.0

    return df


# ── 테스트용 빠른 검증 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import pandas as pd
    import numpy as np

    # 딸기 6개월 모의 데이터
    n = 6
    test_df = pd.DataFrame({
        "farm_id": ["F001"] * n,
        "year": [2023] * n,
        "month": list(range(10, 13)) + list(range(1, 4)),
        "gdd_cumsum": [180, 350, 500, 700, 900, 1200],
        "dli_est": [5.0, 4.0, 3.5, 6.0, 8.0, 10.0],
        "vpd_kpa": [0.6, 0.7, 0.8, 0.5, 0.9, 1.1],
    })

    result = add_aquacrop_features(test_df, crop_en="strawberry")
    print("AquaCrop 피처 추가 결과:")
    print(result[["month", "phenology_stage", "light_saturation",
                   "vpd_stress_cum", "bai", "cwsi"]].to_string(index=False))
    print("\n✅ aquacrop_features.py 정상 동작")
