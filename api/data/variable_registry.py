"""
Variable Registry — 모든 환경·생육 변수의 단일 진실 소스.

각 소스(rda_5yr, eam_hub, eam_2025, asos, manual)에서 들어오는
컬럼명을 canonical_name 으로 통일하고, 단위 변환·유효 범위를 정의한다.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Callable


# ── 유효 범위 검사 ─────────────────────────────────────────────────────────────

def _in_range(mn: float, mx: float) -> Callable[[float], bool]:
    return lambda v: mn <= v <= mx


# ── 변수 정의 ─────────────────────────────────────────────────────────────────

@dataclass
class VariableDef:
    canonical_name: str
    unit: str
    valid_min: float
    valid_max: float
    # 소스 ID → 원본 컬럼명 (None = 해당 소스에 없음)
    source_columns: dict[str, str | None]
    # 값 변환 함수 소스별 (없으면 identity)
    transforms: dict[str, Callable[[float], float]] = field(default_factory=dict)
    # 결측 처리 전략 리스트 (우선순위 순)
    impute_strategies: list[str] = field(default_factory=list)

    def is_valid(self, value: float) -> bool:
        return self.valid_min <= value <= self.valid_max

    def get_source_column(self, source_id: str) -> str | None:
        """소스 ID로 원본 컬럼명 반환. 이암허브는 단위 suffix 제거 후 매칭."""
        col = self.source_columns.get(source_id)
        return col

    def transform(self, source_id: str, value: float) -> float:
        fn = self.transforms.get(source_id)
        return fn(value) if fn else value


# ── 이암허브 컬럼명 정규화 유틸 ───────────────────────────────────────────────

def strip_unit_suffix(col: str) -> str:
    """
    '온도_내부[celsius[℃]]' → '온도_내부'
    '잔존CO2[percent[%]]'   → '잔존CO2'
    """
    return re.sub(r'\[.*\]', '', col).strip()


# ── 정규 컬럼명 → 소스 컬럼명 역매핑 빌더 ────────────────────────────────────

def build_reverse_map(registry: dict[str, VariableDef], source_id: str) -> dict[str, str]:
    """
    Returns {원본컬럼명: canonical_name} for a given source_id.
    이암허브 소스는 strip_unit_suffix 적용 후 키 등록.
    """
    result: dict[str, str] = {}
    for canonical, vdef in registry.items():
        raw_col = vdef.source_columns.get(source_id)
        if raw_col is None:
            continue
        normalized = strip_unit_suffix(raw_col)
        result[normalized] = canonical
    return result


# ── 레지스트리 정의 ────────────────────────────────────────────────────────────

REGISTRY: dict[str, VariableDef] = {

    "temp_internal": VariableDef(
        canonical_name="temp_internal",
        unit="°C",
        valid_min=0.0,
        valid_max=50.0,
        source_columns={
            "rda_5yr":   "온도_내부",
            "eam_hub":   "온도_내부[celsius[℃]]",
            "eam_2025":  "온도_내부",
            "asos":      None,          # DERIVE: avgTa + 4.0 (온실 보정)
            "manual":    "temp_internal",
        },
        transforms={
            "asos": lambda v: v + 4.0,  # 외부→내부 추정 +4°C
        },
        impute_strategies=["SOURCE", "DERIVE:asos", "LOCF:24h", "REGIONAL_MEAN:crop_month"],
    ),

    "temp_external": VariableDef(
        canonical_name="temp_external",
        unit="°C",
        valid_min=-20.0,
        valid_max=45.0,
        source_columns={
            "rda_5yr":   "온도_외부",
            "eam_hub":   "온도_외부[celsius[℃]]",
            "eam_2025":  "온도_외부",
            "asos":      "avgTa",       # 직접 사용
            "manual":    None,
        },
        impute_strategies=["SOURCE", "ASOS", "LOCF:48h"],
    ),

    "humidity_int": VariableDef(
        canonical_name="humidity_int",
        unit="%",
        valid_min=20.0,
        valid_max=100.0,
        source_columns={
            "rda_5yr":   "상대습도_내부",
            "eam_hub":   "상대습도_내부[percent[%]]",
            "eam_2025":  "상대습도_내부",
            "asos":      None,          # 없음
            "manual":    "humidity_int",
        },
        impute_strategies=["SOURCE", "LOCF:6h", "REGIONAL_MEAN:crop_month"],
    ),

    "co2_ppm": VariableDef(
        canonical_name="co2_ppm",
        unit="ppm",
        valid_min=300.0,
        valid_max=2000.0,
        source_columns={
            # 주의: 이암허브는 컬럼명이 [percent[%]]이지만 값은 ppm 단위 (mislabel)
            "rda_5yr":   "잔존이산화탄소(CO2)",
            "eam_hub":   "잔존CO2[percent[%]]",   # 값 그대로 ppm
            "eam_2025":  "잔존CO2",
            "asos":      None,
            "manual":    "co2_ppm",
        },
        impute_strategies=["SOURCE", "KNN:temp_internal+humidity_int:k5", "GLOBAL_MEAN:750"],
    ),

    "solar_rad": VariableDef(
        canonical_name="solar_rad",
        unit="W/m²",
        valid_min=0.0,
        valid_max=1400.0,
        source_columns={
            "rda_5yr":   "일사량_외부",            # W/m²
            "eam_hub":   "일사량_외부[W/m2]",
            "eam_2025":  "일사량_외부",
            "asos":      "hr1MaxIcsr",            # W/m², 1시간 최대치
            "manual":    "solar_rad",
        },
        impute_strategies=["SOURCE", "ASOS:hr1MaxIcsr", "LOCF:6h", "ZERO_AT_NIGHT"],
    ),

    "solar_rad_cumulative": VariableDef(
        canonical_name="solar_rad_cumulative",
        unit="J/cm²",
        valid_min=0.0,
        valid_max=500000.0,
        source_columns={
            "rda_5yr":   "누적일사량_외부",
            "eam_hub":   "누적일사량_외부[J/cm2]",
            "eam_2025":  "누적일사량_외부",
            "asos":      "sumGsr",               # MJ/m² → J/cm² : × 100
            "manual":    None,
        },
        transforms={
            "asos": lambda v: v * 100.0,         # MJ/m² → J/cm²
        },
        impute_strategies=["SOURCE", "CUMSUM:solar_rad"],
    ),

    "soil_temp": VariableDef(
        canonical_name="soil_temp",
        unit="°C",
        valid_min=5.0,
        valid_max=40.0,
        source_columns={
            "rda_5yr":   "토양온도",              # 일부 결측 (파프리카 등)
            "eam_hub":   "토양온도[celsius[℃]]",
            "eam_2025":  "토양온도",
            "asos":      None,
            "manual":    None,
        },
        transforms={},
        impute_strategies=["SOURCE", "DERIVE:temp_internal*0.85", "LOCF:24h"],
    ),

    "wind_speed_ext": VariableDef(
        canonical_name="wind_speed_ext",
        unit="m/s",
        valid_min=0.0,
        valid_max=30.0,
        source_columns={
            "rda_5yr":   "풍속_외부",
            "eam_hub":   "풍속_외부[meter_per_second[m/s]]",
            "eam_2025":  "풍속_외부",
            "asos":      "avgWs",
            "manual":    None,
        },
        impute_strategies=["SOURCE", "ASOS", "ZERO"],
    ),

    "ec_dsm": VariableDef(
        canonical_name="ec_dsm",
        unit="dS/m",
        valid_min=0.5,
        valid_max=5.0,
        source_columns={
            "rda_5yr":   None,          # 전체 결측
            "eam_hub":   None,          # 전체 결측
            "eam_2025":  None,
            "asos":      None,
            "manual":    "ec_dsm",      # 수동 입력만 가능
        },
        impute_strategies=["MANUAL_INPUT", "LOCF:24h", "REGIONAL_MEAN:crop_sido", "GLOBAL_MEAN:2.0"],
    ),

    "rainfall_detect": VariableDef(
        canonical_name="rainfall_detect",
        unit="boolean",
        valid_min=0.0,
        valid_max=1.0,
        source_columns={
            "rda_5yr":   "강우감지",
            "eam_hub":   "강우감지",
            "eam_2025":  "강우감지",
            "asos":      None,
            "manual":    None,
        },
        impute_strategies=["SOURCE", "ZERO"],
    ),
}

# ── 생육 변수 레지스트리 (별도) ────────────────────────────────────────────────

GROWTH_REGISTRY: dict[str, VariableDef] = {

    "plant_height_cm": VariableDef(
        canonical_name="plant_height_cm",
        unit="cm",
        valid_min=1.0,
        valid_max=800.0,
        source_columns={
            "rda_growth":  "초장",
            "eam_growth":  "초장[centimeter[cm]]",
            "eam_2025g":   "초장",
        },
        impute_strategies=["SOURCE", "LOCF:1w"],
    ),

    "leaf_count": VariableDef(
        canonical_name="leaf_count",
        unit="개",
        valid_min=1.0,
        valid_max=60.0,
        source_columns={
            "rda_growth":  "엽수",
            "eam_growth":  "엽수[개]",
            "eam_2025g":   "엽수",
        },
        impute_strategies=["SOURCE", "LOCF:1w"],
    ),

    "fruit_set_count": VariableDef(
        canonical_name="fruit_set_count",
        unit="개",
        valid_min=0.0,
        valid_max=50.0,
        source_columns={
            "rda_growth":  "화방별착과수",
            "eam_growth":  "화방별착과수[개]",
            "eam_2025g":   "화방별착과수",
        },
        impute_strategies=["SOURCE", "ZERO"],
    ),

    "stem_diameter_mm": VariableDef(
        canonical_name="stem_diameter_mm",
        unit="mm",
        valid_min=1.0,
        valid_max=30.0,
        source_columns={
            "rda_growth":  "관부직경",      # 딸기
            "eam_growth":  "줄기굵기[millimeter[mm]]",  # 토마토
            "eam_2025g":   "관부직경",
        },
        impute_strategies=["SOURCE", "LOCF:1w"],
    ),
}


# ── 편의 함수 ─────────────────────────────────────────────────────────────────

def get_canonical(source_id: str, raw_col: str) -> str | None:
    """
    주어진 소스의 원본 컬럼명 → canonical_name 반환.
    이암허브처럼 단위 suffix가 붙어있어도 처리.
    """
    normalized = strip_unit_suffix(raw_col)
    for canonical, vdef in REGISTRY.items():
        src_col = vdef.source_columns.get(source_id)
        if src_col and strip_unit_suffix(src_col) == normalized:
            return canonical
    # 생육 레지스트리도 탐색
    for canonical, vdef in GROWTH_REGISTRY.items():
        src_col = vdef.source_columns.get(source_id)
        if src_col and strip_unit_suffix(src_col) == normalized:
            return canonical
    return None


def apply_transform(source_id: str, canonical: str, value: float) -> float:
    """값 단위 변환 적용."""
    vdef = REGISTRY.get(canonical) or GROWTH_REGISTRY.get(canonical)
    if vdef is None:
        return value
    return vdef.transform(source_id, value)


def validate(canonical: str, value: float) -> bool:
    """유효 범위 검사."""
    vdef = REGISTRY.get(canonical) or GROWTH_REGISTRY.get(canonical)
    if vdef is None:
        return True
    return vdef.is_valid(value)


# ── 품목별 GDD 파라미터 (초기값 — Phase 2에서 실데이터로 보정) ─────────────────

GDD_PARAMS: dict[str, dict] = {
    "딸기":      {"base_temp_c": 6.0,  "gdd_to_first_harvest": 450, "gdd_per_flush": 180},
    "방울토마토": {"base_temp_c": 10.0, "gdd_to_first_harvest": 600, "gdd_per_flush": 200},
    "완숙토마토": {"base_temp_c": 10.0, "gdd_to_first_harvest": 650, "gdd_per_flush": 220},
    "참외":      {"base_temp_c": 12.0, "gdd_to_first_harvest": 700, "gdd_per_flush": 240},
    "오이":      {"base_temp_c": 12.0, "gdd_to_first_harvest": 400, "gdd_per_flush": 150},
}
