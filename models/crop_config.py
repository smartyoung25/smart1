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
YEARS      = [2018, 2019, 2020, 2021, 2022, 2023, 2025]   # 2023: SANWOO 딸기, 2025: 조남헌 파프리카
SUPP_YEARS = [2023, 2025]   # 보조 연도 - CV 테스트 폴드에서 제외, 항상 train에만 포함


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

    # ── ET 관수 최적화 필드 (FAO-56 Kc 작물계수) ───────────────────────────
    # Kc (crop coefficient): ETc = ET₀ × Kc  [FAO-56 Table 12, Allen et al. 1998]
    # stages: "initial" (정식~뿌리활착), "dev" (생육), "mid" (최성기), "late" (수확말기)
    kc_stages: dict[str, float] = field(
        default_factory=lambda: {"initial": 0.3, "dev": 0.7, "mid": 1.05, "late": 0.85}
    )
    # 1회 관수 목표량 (mm/day): ETc와 비교하여 부족량 보충 기준
    irrigation_target_mm_day: float = 3.5
    # 스마트팜 배액률 목표 (%) — 슬라브/암면 재배시 15~25% 배액이 최적
    drain_target_pct: float = 20.0


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
        # FAO-56 딸기 Kc (암면 슬라브 스마트팜 기준, RDA 농가 측정값 보정)
        kc_stages={"initial": 0.40, "dev": 0.70, "mid": 0.85, "late": 0.75},
        irrigation_target_mm_day=2.5,   # 딸기: 1.5~3.5mm/day (암면 소형 슬라브)
        drain_target_pct=20.0,
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
        # FAO-56 토마토(소과) Kc — 유리온실 연속재배 기준 [Marcelis et al.]
        kc_stages={"initial": 0.45, "dev": 0.85, "mid": 1.15, "late": 0.90},
        irrigation_target_mm_day=4.0,
        drain_target_pct=20.0,
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
        # FAO-56 토마토(대과) Kc — 파이프라인 트레이닝용 유리온실 기준
        kc_stages={"initial": 0.45, "dev": 0.90, "mid": 1.20, "late": 0.90},
        irrigation_target_mm_day=4.5,
        drain_target_pct=20.0,
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
        min_train_samples=60,  # n=42 → Ridge 폴백 강제 (XGBoost 과적합 방지)
        area_default_m2=3800.0,
        season_months=[3, 4, 5, 6, 7, 8],
        heating_months=[3, 4],
        # FAO-56 멜론/참외 Kc [Allen et al. 1998, Table 12]
        kc_stages={"initial": 0.50, "dev": 0.80, "mid": 1.00, "late": 0.75},
        irrigation_target_mm_day=3.5,
        drain_target_pct=15.0,  # 토양재배 기준 낮은 배액률
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
        # FAO-56 피망/파프리카 Kc [Allen et al. 1998 + RDA 2022 보정]
        kc_stages={"initial": 0.40, "dev": 0.80, "mid": 1.10, "late": 0.90},
        irrigation_target_mm_day=4.0,
        drain_target_pct=20.0,
    ),
    "오이": CropConfig(
        crop_ko="오이",
        crop_en="cucumber",
        t_base=12.0,
        growth_cols=["초장", "마디수", "줄기굵기", "엽장", "엽폭", "엽수"],
        opt_temp_range=(22.0, 30.0),
        opt_humid_range=(65.0, 85.0),
        opt_co2_range=(400.0, 1200.0),
        env_to_growth_lag=1,   # 오이 생육 빠름
        harvest_lag=1,
        area_default_m2=1000.0,
        season_months=list(range(1, 13)),
        heating_months=[11, 12, 1, 2, 3],
        # FAO-56 오이 Kc [Allen et al. 1998, Table 12 — fresh market, greenhouse]
        kc_stages={"initial": 0.60, "dev": 0.90, "mid": 1.00, "late": 0.75},
        irrigation_target_mm_day=4.0,
        drain_target_pct=20.0,
    ),
    # ── 제주 주력 노지작물 (화산회토 노지 재배) ──────────────────────────────
    "감귤": CropConfig(
        crop_ko="감귤",
        crop_en="citrus",
        t_base=13.0,           # 감귤 생육 기준온도 (아열대성)
        growth_cols=["수고", "수관폭", "엽수", "착과수", "과경"],
        opt_temp_range=(15.0, 25.0),
        opt_humid_range=(60.0, 80.0),
        opt_co2_range=(380.0, 600.0),   # 노지 — 대기 CO₂ 수준
        env_to_growth_lag=3,            # 다년생 — 환경→생육 지연 큼
        harvest_lag=3,
        area_default_m2=3000.0,
        season_months=list(range(1, 13)),  # 상록 다년생
        heating_months=[],                  # 노지 무가온
        # FAO-56 Citrus Kc [Allen 1998, Table 12 — 70% ground cover, no frost]
        kc_stages={"initial": 0.65, "dev": 0.70, "mid": 0.70, "late": 0.65},
        irrigation_target_mm_day=3.0,
        drain_target_pct=0.0,           # 노지 — 배액 개념 없음
    ),
    "월동무": CropConfig(
        crop_ko="월동무",
        crop_en="winter_radish",
        t_base=5.0,
        growth_cols=["초장", "엽수", "엽장", "근장", "근경"],
        opt_temp_range=(5.0, 20.0),
        opt_humid_range=(60.0, 85.0),
        opt_co2_range=(380.0, 500.0),
        env_to_growth_lag=1,
        harvest_lag=1,
        area_default_m2=5000.0,
        season_months=[9, 10, 11, 12, 1, 2, 3],   # 제주 월동 작형
        heating_months=[],
        # FAO-56 Radish Kc [Allen 1998 — short season root crop]
        kc_stages={"initial": 0.70, "dev": 0.85, "mid": 0.90, "late": 0.85},
        irrigation_target_mm_day=3.5,
        drain_target_pct=0.0,
    ),
    "당근": CropConfig(
        crop_ko="당근",
        crop_en="carrot",
        t_base=5.0,
        growth_cols=["초장", "엽수", "근장", "근경"],
        opt_temp_range=(8.0, 22.0),
        opt_humid_range=(60.0, 80.0),
        opt_co2_range=(380.0, 500.0),
        env_to_growth_lag=1,
        harvest_lag=2,
        area_default_m2=4000.0,
        season_months=[8, 9, 10, 11, 12, 1, 2, 3],  # 제주 가을·월동 당근
        heating_months=[],
        # FAO-56 Carrot Kc [Allen 1998, Table 12]
        kc_stages={"initial": 0.70, "dev": 0.90, "mid": 1.05, "late": 0.95},
        irrigation_target_mm_day=3.5,
        drain_target_pct=0.0,
    ),
    "양배추": CropConfig(
        crop_ko="양배추",
        crop_en="cabbage",
        t_base=5.0,
        growth_cols=["초장", "엽수", "엽장", "엽폭", "결구중"],
        opt_temp_range=(8.0, 20.0),
        opt_humid_range=(60.0, 85.0),
        opt_co2_range=(380.0, 500.0),
        env_to_growth_lag=1,
        harvest_lag=2,
        area_default_m2=4000.0,
        season_months=[9, 10, 11, 12, 1, 2, 3],     # 제주 월동 양배추
        heating_months=[],
        # FAO-56 Cabbage Kc [Allen 1998, Table 12]
        kc_stages={"initial": 0.70, "dev": 0.95, "mid": 1.05, "late": 0.95},
        irrigation_target_mm_day=3.5,
        drain_target_pct=0.0,
    ),
    "마늘": CropConfig(
        crop_ko="마늘",
        crop_en="garlic",
        t_base=4.0,
        growth_cols=["초장", "엽수", "엽초경", "구중", "구경"],
        opt_temp_range=(5.0, 20.0),
        opt_humid_range=(60.0, 80.0),
        opt_co2_range=(380.0, 500.0),
        env_to_growth_lag=2,
        harvest_lag=3,
        area_default_m2=3300.0,
        season_months=[9, 10, 11, 12, 1, 2, 3, 4, 5, 6],  # 제주 난지형 마늘 가을파종~초여름수확
        heating_months=[],
        # FAO-56 Garlic Kc [Allen 1998, Table 12]
        kc_stages={"initial": 0.70, "dev": 0.90, "mid": 1.00, "late": 0.70},
        irrigation_target_mm_day=3.0,
        drain_target_pct=0.0,
    ),
    "양파": CropConfig(
        crop_ko="양파",
        crop_en="onion",
        t_base=4.5,
        growth_cols=["초장", "엽수", "엽초경", "구중", "구경"],
        opt_temp_range=(5.0, 22.0),
        opt_humid_range=(60.0, 80.0),
        opt_co2_range=(380.0, 500.0),
        env_to_growth_lag=2,
        harvest_lag=3,
        area_default_m2=3300.0,
        season_months=[9, 10, 11, 12, 1, 2, 3, 4, 5, 6],  # 가을정식~초여름수확
        heating_months=[],
        # FAO-56 Onion(dry) Kc [Allen 1998, Table 12]
        kc_stages={"initial": 0.70, "dev": 0.95, "mid": 1.05, "late": 0.75},
        irrigation_target_mm_day=3.0,
        drain_target_pct=0.0,
    ),
}

# ── 작기 길이(개월) — 비용·수확량 시즌화용 SSOT (E2E 2026-08-07) ──────────────
#   ★ CropConfig.season_months(위)와 개념이 다르다: 저건 '활동 캘린더월 리스트'
#     (예: 오이=1~12월 연중 하우스 가동)로 학습·기후 필터용. 이건 '1작기(파종~수확
#     종료) 기간의 개월수'로, 월 단위 비용/수확량을 시즌 총액으로 환산할 때 쓴다.
#   구: model_loader·m2_yield·erp_calculator 3곳에 각각 중복 정의되어 값이 갈렸다
#     (오이 8 vs 5, 딸기 6 vs 8 등). 여기 단일 정본으로 통합.
SEASON_LENGTH_MONTHS: dict[str, int] = {
    "딸기":       6,
    "방울토마토": 8,
    "완숙토마토": 8,
    "참외":       4,
    "파프리카":  10,
    "오이":       5,   # 촉성/반촉성 단작 ~4~5개월 (E2E 캘리브레이션)
}


def get_season_length_months(crop_ko: str, default: int = 8) -> int:
    """작목의 1작기 개월수(비용·수확량 시즌화용). 미등록 작목은 default."""
    return SEASON_LENGTH_MONTHS.get(crop_ko, default)


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
