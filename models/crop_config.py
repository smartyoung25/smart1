"""작목별 설정 중앙 관리 모듈.

기존 train_multi_crop_pipeline.py에 분산되어 있던 CropConfig 및
CROP_CONFIGS를 통합하고, 4-Stage 파이프라인에 필요한 필드를 추가한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ── 공통 환경 변수 매핑 ────────────────────────────────────────────────────────

ENV_COLS: dict[str, str] = {
    "온도_내부":     "temp_internal",
    "상대습도_내부": "humidity_int",
    "잔존CO2":       "co2_ppm",
    "토양온도":      "soil_temp",
    "일사량_외부":   "solar_rad",
    "온도_외부":     "temp_external",
    "풍속_외부":     "wind_speed",
}

ENV_HARD_BOUNDS: dict[str, tuple[float, float]] = {
    "temp_internal": (-5.0,  55.0),
    "humidity_int":  ( 0.0, 100.0),
    "co2_ppm":       ( 0.0, 5000.0),
    "soil_temp":     (-5.0,  50.0),
    "solar_rad":     ( 0.0, 1500.0),
    "temp_external": (-20.0, 45.0),
    "wind_speed":    ( 0.0,  30.0),
}

# 데이터 경로
ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "기초자료" / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터"
OUT_DIR  = ROOT / "models" / "artifacts"
DOCS_DIR = ROOT / "docs"
YEARS    = [2018, 2019, 2020, 2021, 2022]


# ── 작목 설정 ─────────────────────────────────────────────────────────────────

@dataclass
class CropConfig:
    crop_ko:    str                          # 한국어 품목명
    crop_en:    str                          # 영문 식별자 (파일명 사용)
    t_base:     float                        # GDD 기준온도 (°C)
    growth_cols: list[str]                   # 생육 측정 변수

    # 환경 최적화 탐색 범위
    opt_temp_range:  tuple[float, float] = (14.0, 28.0)
    opt_humid_range: tuple[float, float] = (50.0, 85.0)
    opt_co2_range:   tuple[float, float] = (400.0, 1600.0)

    # ── 4-Stage 신규 필드 ───────────────────────────────────────────────────
    env_to_growth_lag: int   = 2      # 환경→생육 lag (월 단위)
    harvest_lag:       int   = 1      # 생육→수확 lag (월 단위)
    yield_log_transform: bool = True  # Stage2 타겟 log1p 변환 여부
    min_train_samples: int   = 50     # Ridge 폴백 임계값
    area_default_m2: float   = 1200.0 # 면적 정보 없을 때 최후 기본값
    season_months:  list[int] = field(default_factory=lambda: list(range(1, 13)))
    heating_months: list[int] = field(default_factory=lambda: [11, 12, 1, 2, 3])


CROP_CONFIGS: dict[str, CropConfig] = {
    "딸기": CropConfig(
        crop_ko="딸기",
        crop_en="strawberry",
        t_base=6.0,
        growth_cols=["초장", "엽수", "엽장", "엽폭", "화방별착과수"],
        opt_temp_range=(14.0, 22.0),
        opt_humid_range=(55.0, 80.0),
        opt_co2_range=(600.0, 1200.0),
        env_to_growth_lag=2,
        harvest_lag=1,
        area_default_m2=1200.0,
        season_months=[10, 11, 12, 1, 2, 3, 4, 5],
        heating_months=[11, 12, 1, 2, 3],
    ),
    "방울토마토": CropConfig(
        crop_ko="방울토마토",
        crop_en="cherry_tomato",
        t_base=10.0,
        growth_cols=["초장", "생장길이", "엽수", "엽장", "엽폭", "줄기굵기",
                     "화방별꽃수", "화방별개화수", "화방별착과수"],
        opt_temp_range=(18.0, 28.0),
        opt_humid_range=(55.0, 80.0),
        opt_co2_range=(600.0, 1400.0),
        env_to_growth_lag=2,
        harvest_lag=1,
        area_default_m2=1600.0,
        season_months=list(range(1, 13)),
        heating_months=[11, 12, 1, 2, 3],
    ),
    "완숙토마토": CropConfig(
        crop_ko="완숙토마토",
        crop_en="tomato",
        t_base=10.0,
        growth_cols=["초장", "생장길이", "엽수", "엽장", "엽폭", "줄기굵기",
                     "화방별꽃수", "화방별개화수", "화방별착과수", "개화군", "착과군"],
        opt_temp_range=(18.0, 28.0),
        opt_humid_range=(55.0, 80.0),
        opt_co2_range=(600.0, 1400.0),
        env_to_growth_lag=2,
        harvest_lag=1,
        area_default_m2=1400.0,
        season_months=list(range(1, 13)),
        heating_months=[11, 12, 1, 2, 3],
    ),
    "참외": CropConfig(
        crop_ko="참외",
        crop_en="melon",
        t_base=12.0,
        growth_cols=["초장", "마디수", "평균절간장", "줄기굵기",
                     "엽장", "엽폭", "엽수", "암꽃수", "착과수"],
        opt_temp_range=(22.0, 32.0),
        opt_humid_range=(55.0, 75.0),
        opt_co2_range=(400.0, 1200.0),
        env_to_growth_lag=1,   # 참외는 생육 빠름
        harvest_lag=1,
        min_train_samples=30,  # 샘플 부족 → 폴백 적극 활용
        area_default_m2=3800.0,
        season_months=[3, 4, 5, 6, 7, 8],
        heating_months=[3, 4],
    ),
    "파프리카": CropConfig(
        crop_ko="파프리카",
        crop_en="paprika",
        t_base=10.0,
        growth_cols=["초장", "생장길이", "엽수", "엽장", "엽폭", "줄기굵기",
                     "화방높이", "개화마디", "착과마디"],
        opt_temp_range=(20.0, 28.0),
        opt_humid_range=(60.0, 80.0),
        opt_co2_range=(600.0, 1400.0),
        env_to_growth_lag=2,
        harvest_lag=2,         # 파프리카 착과→수확 기간 길다
        area_default_m2=2500.0,
        season_months=list(range(1, 13)),
        heating_months=[11, 12, 1, 2, 3],
    ),
}

# 영문 → 한글 역조회
CROP_EN_TO_KO: dict[str, str] = {v.crop_en: k for k, v in CROP_CONFIGS.items()}


def get_config(crop_ko: str) -> CropConfig:
    """작목명(한국어)으로 CropConfig 반환. 없으면 딸기 기본값."""
    return CROP_CONFIGS.get(crop_ko, CROP_CONFIGS["딸기"])


def get_artifact_dir(crop_en: str) -> Path:
    """작목별 아티팩트 디렉토리 (자동 생성)."""
    d = OUT_DIR / crop_en
    d.mkdir(parents=True, exist_ok=True)
    return d
