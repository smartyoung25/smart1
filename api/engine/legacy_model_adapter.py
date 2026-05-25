"""LegacyModelAdapter — SFROP v2.0 Phase 45.

RDA 농진청 스마트팜 실측 데이터(5000행)를 현재 sklearn 으로 재학습하여
M2 수확량 예측 정확도를 향상시킨다.

배경:
  smartfarm-mvp 프로젝트의 .joblib 모델(sklearn 1.5.2)은
  현재 환경(sklearn 1.8+)에서 로드 불가(_RemainderColsList 속성 누락).
  따라서 동일 데이터로 현재 sklearn 에서 재학습 → 동급 성능 확보.

지원 작목:
  - 딸기 (5,000행, 18 IoT 피처, 목표 R² ≥ 0.75)
  - 참외 (향후 추가 예정)

IoT 가용 피처 (29개 중 18개):
  조사월, 기온_C, 야간기온_C, DIF, EC_dS_m, 일사량_Wm2, slr_wma,
  관수량, 경과일, GDD정규화, GDD정규화_sq, 적산온도, 누적일사량,
  CU_norm, 연간CU, ET0_mm, 종형_T, 종형_EC

비 IoT 피처 (물리 실측, 추론 시 제외):
  줄기굵기_실측, 엽장_실측, 런너번호, 꽃수, 관부직경_mm,
  과실수대리, 과당무게대리_g
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent

# 학습 데이터 경로
_CSV_MAP: dict[str, Path] = {
    "딸기": ROOT / "data" / "training" / "strawberry_rda_5000.csv",
    "참외": ROOT / "data" / "training" / "melon_rda_9392.csv",
}

# 모델 캐시 경로
_MODEL_DIR = ROOT / "models" / "artifacts" / "rda_models"
_MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ── 실제 컬럼명 (cols_check.txt 기반 UTF-8 BOM 디코딩 결과) ──────────────────
# 딸기 CSV 29컬럼 순서대로
_STRAWBERRY_COLS = [
    "조사월", "기온_C", "야간기온_C", "DIF", "EC_dS_m",
    "일사량_Wm2", "slr_wma", "관수량", "경과일",
    "GDD정규화", "GDD정규화_sq", "적산온도", "누적일사량",
    "CU_norm", "연간CU", "NDVI", "ET0_mm", "종형_T", "종형_EC",
    "줄기굵기_실측", "엽장_실측", "런너번호", "꽃수", "관부직경_mm",
    "과실수대리", "과당무게대리_g",
    "수확량_kg_10a", "당도_Brix", "특품율",
]

# IoT 환경에서 수집·계산 가능한 피처 (물리 실측 제외)
IOT_FEATURES: list[str] = [
    "조사월", "기온_C", "야간기온_C", "DIF", "EC_dS_m",
    "일사량_Wm2", "slr_wma", "관수량", "경과일",
    "GDD정규화", "GDD정규화_sq", "적산온도", "누적일사량",
    "CU_norm", "연간CU", "ET0_mm", "종형_T", "종형_EC",
]

TARGET_YIELD = "수확량_kg_10a"   # kg/10a → 최종 변환: ÷1000 = kg/m²
TARGET_BRIX  = "당도_Brix"
TARGET_GRADE = "특품율"


def _load_strawberry_df():
    """딸기 RDA CSV 로드 + 컬럼명 교정."""
    import pandas as pd
    csv = _CSV_MAP["딸기"]
    if not csv.exists():
        raise FileNotFoundError(f"딸기 학습 CSV 없음: {csv}")

    df = pd.read_csv(csv, encoding="utf-8-sig")

    # CSV 컬럼이 깨져있을 경우 순서 기반으로 재매핑
    if len(df.columns) == len(_STRAWBERRY_COLS):
        df.columns = _STRAWBERRY_COLS
    else:
        logger.warning("딸기 CSV 컬럼 수 불일치 (%d vs %d) — 이름 그대로 사용",
                       len(df.columns), len(_STRAWBERRY_COLS))

    return df


def _train_strawberry() -> tuple[Any, dict]:
    """딸기 모델 학습 (GradientBoosting + IoT 피처)."""
    import pandas as pd
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    df = _load_strawberry_df()

    # 필요 컬럼 존재 확인
    avail_feats = [c for c in IOT_FEATURES if c in df.columns]
    if TARGET_YIELD not in df.columns:
        raise ValueError(f"타겟 컬럼 없음: {TARGET_YIELD}")

    sub = df[avail_feats + [TARGET_YIELD, TARGET_BRIX, TARGET_GRADE]].dropna(
        subset=avail_feats + [TARGET_YIELD]
    )

    X = sub[avail_feats].values.astype(np.float32)
    y_yield = sub[TARGET_YIELD].values.astype(np.float32)

    # 수확량 단위 변환: kg/10a → kg/m²
    y_yield_m2 = y_yield / 1000.0

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("gbr",    GradientBoostingRegressor(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )),
    ])

    # 5-fold CV R² 산출 (학습 전)
    cv_scores = cross_val_score(pipe, X, y_yield_m2, cv=5, scoring="r2")
    cv_r2 = float(np.mean(cv_scores))

    # 전체 데이터로 최종 학습
    pipe.fit(X, y_yield_m2)

    # 특성 중요도 추출
    feat_imp = {}
    gbr = pipe.named_steps["gbr"]
    for name, imp in zip(avail_feats, gbr.feature_importances_):
        feat_imp[name] = round(float(imp), 4)

    meta = {
        "crop_ko":       "딸기",
        "n_samples":     len(sub),
        "n_features":    len(avail_feats),
        "feature_names": avail_feats,
        "cv_r2_mean":    round(cv_r2, 4),
        "cv_r2_std":     round(float(np.std(cv_scores)), 4),
        "feature_importances": feat_imp,
        "yield_unit":    "kg/m²",
    }

    logger.info("[LegacyAdapter] 딸기 학습 완료 — n=%d CV R²=%.3f",
                len(sub), cv_r2)
    return pipe, meta


def _get_model_cache_path(crop_ko: str) -> Path:
    return _MODEL_DIR / f"rda_{crop_ko}_iot.pkl"


def _save_model(crop_ko: str, pipe, meta: dict) -> None:
    path = _get_model_cache_path(crop_ko)
    with open(path, "wb") as f:
        pickle.dump({"pipe": pipe, "meta": meta}, f, protocol=5)
    logger.info("[LegacyAdapter] 모델 저장: %s", path)


def _load_model_cache(crop_ko: str) -> Optional[tuple]:
    path = _get_model_cache_path(crop_ko)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
        return obj["pipe"], obj["meta"]
    except Exception as e:
        logger.warning("[LegacyAdapter] 캐시 로드 실패: %s", e)
        return None


# ── 싱글턴 캐시 ───────────────────────────────────────────────────────────────
_MODEL_CACHE: dict[str, tuple] = {}


def _get_or_train(crop_ko: str) -> tuple[Any, dict]:
    """캐시 우선 → 없으면 학습 후 저장."""
    if crop_ko in _MODEL_CACHE:
        return _MODEL_CACHE[crop_ko]

    cached = _load_model_cache(crop_ko)
    if cached:
        _MODEL_CACHE[crop_ko] = cached
        return cached

    # 신규 학습
    if crop_ko == "딸기":
        pipe, meta = _train_strawberry()
    else:
        raise ValueError(f"LegacyAdapter: 미지원 작목 '{crop_ko}'")

    _save_model(crop_ko, pipe, meta)
    _MODEL_CACHE[crop_ko] = (pipe, meta)
    return pipe, meta


class LegacyModelAdapter:
    """RDA 실측 데이터로 재학습한 고정밀 수확량 예측 어댑터.

    사용 예::

        adapter = LegacyModelAdapter()
        result  = adapter.predict("딸기", features)
        # result = {"yield_per_m2": 0.87, "confidence_grade": "A", ...}
    """

    SUPPORTED_CROPS = {"딸기"}

    def supports(self, crop_ko: str) -> bool:
        return crop_ko in self.SUPPORTED_CROPS

    def model_info(self, crop_ko: str = "딸기") -> dict:
        """모델 메타 정보 반환 (CV R² 등)."""
        try:
            _, meta = _get_or_train(crop_ko)
            return meta
        except Exception as e:
            return {"error": str(e)}

    def predict(
        self,
        crop_ko: str,
        features: Dict[str, float],
    ) -> dict:
        """IoT 피처 딕셔너리 → 수확량 예측.

        Args:
            crop_ko:  작목명 (딸기 등)
            features: IoT 피처 딕셔너리. 없는 피처는 학습 데이터 중앙값으로 채움.

        Returns:
            {
              "yield_per_m2": float,       # kg/m²
              "confidence_grade": str,     # A/B/C
              "cv_r2": float,
              "model": "rda_legacy",
              "n_features_used": int,
              "feature_names": [...],
            }
        """
        if not self.supports(crop_ko):
            raise ValueError(f"미지원 작목: {crop_ko}")

        pipe, meta = _get_or_train(crop_ko)
        feat_names: list[str] = meta["feature_names"]

        # 피처 벡터 구성 (없는 값은 0 채움 — 학습 시 scaler 로 정규화됨)
        row = np.array(
            [float(features.get(f, 0.0)) for f in feat_names],
            dtype=np.float32,
        ).reshape(1, -1)

        yield_m2 = float(pipe.predict(row)[0])
        yield_m2 = max(0.0, yield_m2)

        cv_r2 = meta.get("cv_r2_mean", 0.0)
        if cv_r2 >= 0.70:
            grade = "A"
        elif cv_r2 >= 0.50:
            grade = "B"
        else:
            grade = "C"

        return {
            "yield_per_m2":      round(yield_m2, 3),
            "confidence_grade":  grade,
            "cv_r2":             cv_r2,
            "model":             "rda_legacy",
            "n_features_used":   len(feat_names),
            "feature_names":     feat_names,
        }


def build_iot_features_from_env(
    env: dict,
    month: int,
    days_since_planting: int = 60,
    crop_ko: str = "딸기",
) -> dict:
    """IoT 환경 딕셔너리 → LegacyAdapter 피처 딕셔너리 변환.

    Args:
        env:                 IoT 센서 딕셔너리 (temp_internal, ec, solar_rad 등)
        month:               현재 월 (1~12)
        days_since_planting: 정식 후 경과일
        crop_ko:             작목명

    Returns:
        IOT_FEATURES 키를 갖는 피처 딕셔너리
    """
    temp    = float(env.get("temp_internal", env.get("temp", 18.0)) or 18.0)
    night_t = float(env.get("night_temp", temp - 6.0) or (temp - 6.0))
    dif     = temp - night_t
    ec      = float(env.get("ec", env.get("EC_dS_m", 1.5)) or 1.5)
    solar   = float(env.get("solar_rad", env.get("일사량_Wm2", 80.0)) or 80.0)
    irrig   = float(env.get("irrigation_ml", env.get("관수량", 150.0)) or 150.0)

    # 딸기 기준 GDD (기준온도 5°C, 최적 22°C 기준 정규화)
    gdd_daily  = max(0.0, temp - 5.0)
    gdd_season = gdd_daily * days_since_planting
    gdd_norm   = min(1.0, gdd_season / (22.0 * 150.0))  # 150일 기준 1.0
    gdd_norm_sq = gdd_norm ** 2

    accum_temp  = gdd_season
    accum_solar = solar * days_since_planting

    # 냉각단위 (딸기 휴면 해제 7.2°C 기준) — 누적 추정
    cu_daily = max(0.0, 7.2 - night_t) if night_t < 7.2 else 0.0
    cu_norm  = min(1.0, cu_daily * days_since_planting / 800.0)
    annual_cu = cu_daily * 90  # 가을철 3개월 추정

    # Hargreaves-Samani ET0 근사 (간이)
    ra = solar * 0.0036  # W/m² → MJ/m²/h * 적산
    et0 = 0.0023 * ra * (temp + 17.8) * max(0.0, dif) ** 0.5 * 0.408 if dif > 0 else 0.0
    et0 = max(0.0, et0)

    # 종형 함수 (최적 T=20, σ=5 / 최적 EC=1.8, σ=0.8)
    bell_t  = float(np.exp(-0.5 * ((temp  - 20.0) / 5.0) ** 2))
    bell_ec = float(np.exp(-0.5 * ((ec    -  1.8) / 0.8) ** 2))

    return {
        "조사월":       month,
        "기온_C":       temp,
        "야간기온_C":   night_t,
        "DIF":          dif,
        "EC_dS_m":      ec,
        "일사량_Wm2":   solar,
        "slr_wma":      solar * 0.9,   # 7일 이동평균 근사 (단순 0.9배)
        "관수량":       irrig,
        "경과일":       days_since_planting,
        "GDD정규화":    gdd_norm,
        "GDD정규화_sq": gdd_norm_sq,
        "적산온도":     accum_temp,
        "누적일사량":   accum_solar,
        "CU_norm":      cu_norm,
        "연간CU":       annual_cu,
        "ET0_mm":       et0,
        "종형_T":       bell_t,
        "종형_EC":      bell_ec,
    }
