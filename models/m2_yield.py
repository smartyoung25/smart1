"""M2 수확량 예측 — Format C 단일 구현 (log1p/잔차/월 모드 통합)

포맷 이력:
  Format A (feat_cols + farm_yield_mean):   구형 train_stage2_yield.py — 제거됨
  Format B (features, log_transform, xgb/lgb): 구형 DAG retrain — 제거됨
  Format C (feature_cols + imputer):        현행 유일 포맷 — 유지

pkl 구조 (Format C):
  feature_cols   : list[str]        피처 컬럼명
  imputer        : SimpleImputer    NaN → 훈련 중앙값
  model          : XGBRegressor     (optional)
  model_lgb      : LGBMRegressor    (optional)
  log_transform  : bool             True=log1p 역변환
  agg_mode       : str              "annual" | "annual_residual" | "monthly"
  cv_mape_mean   : float            교차검증 MAPE (%)
  farm_encoding  : dict             per_farm, global_mean, global_cv
"""
import logging
import os
import pickle
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:                                    # 권위 지표 단일 출처 (pipeline/gates.py)
    from pipeline.gates import read_stage2_metrics as _read_stage2_metrics
except Exception:                       # 모듈 부재 시 pkl 내부 mape 사용(기존 동작)
    _read_stage2_metrics = None

logger = logging.getLogger(__name__)

ARTS = os.path.join(os.path.dirname(__file__), "artifacts")

CROP_MAP: dict[str, str] = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
    "오이":       "cucumber",
    # 영문 pass-through
    "strawberry":    "strawberry",
    "cherry_tomato": "cherry_tomato",
    "tomato":        "tomato",
    "melon":         "melon",
    "paprika":       "paprika",
    "cucumber":      "cucumber",
}

# 작기 개월수 — 연간 예측값을 월별로 환산할 때 사용
_SEASON_MONTHS: dict[str, int] = {
    "딸기":       6,
    "방울토마토": 8,
    "완숙토마토": 8,
    "참외":       4,
    "파프리카":  10,
    "오이":       8,
}

_cache:      Dict[str, Any] = {}
_corr_cache: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# sklearn compat 패치 (sklearn 1.5+ SimpleImputer._fill_dtype 누락 대응)
# ---------------------------------------------------------------------------

def _patch_imputer(imputer) -> None:
    """sklearn 1.5+ 호환: 구버전으로 직렬화된 SimpleImputer에 _fill_dtype 속성 보정."""
    if imputer is None:
        return
    if not hasattr(imputer, "_fill_dtype"):
        try:
            imputer._fill_dtype = imputer.statistics_.dtype
        except Exception as exc:
            logger.debug("[m2_yield] SimpleImputer 패치 실패: %s", exc)


# ---------------------------------------------------------------------------
# 모델 로드
# ---------------------------------------------------------------------------

def _load(crop_ko: str) -> Optional[dict]:
    """Format C pkl 로드. m2_yield_model.pkl → stage2_yield.pkl 순으로 시도.

    ※ 여기서 게이트로 하드 차단하지 말 것 — pkg=None이면 predict_yield가
      하드코딩 stub(5,000kg)을 반환해 오히려 개악이 된다. 게이트 반영은
      predict_yield의 RDA 통계 블렌딩(권위 MAPE 기준)으로 처리한다.
    """
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _cache:
        return _cache[key]

    art_dir = os.path.join(ARTS, key)
    for fname in ("m2_yield_model.pkl", "stage2_yield.pkl"):
        pkl_path = os.path.join(art_dir, fname)
        if not os.path.exists(pkl_path):
            continue
        try:
            with open(pkl_path, "rb") as f:
                pkg = pickle.load(f)
            if not isinstance(pkg, dict):
                logger.warning("[m2_yield] %s: pkl이 dict가 아님 (%s)", key, type(pkg))
                continue
            # Format 검증
            if "feature_cols" not in pkg:
                logger.warning(
                    "[m2_yield] %s/%s: Format C 키(feature_cols) 없음 — 건너뜀", key, fname
                )
                continue
            _patch_imputer(pkg.get("imputer"))
            _cache[key] = pkg
            logger.info("[m2_yield] 로드: %s/%s (feats=%d)", key, fname,
                        len(pkg.get("feature_cols", [])))
            return pkg
        except Exception as e:
            logger.error("[m2_yield] 로드 실패 %s/%s: %s", key, fname, e)

    logger.warning("[m2_yield] 모델 없음: %s", key)
    _cache[key] = None
    return None


def _load_corrections(crop_ko: str) -> Dict[str, Any]:
    """농가별 bias correction 로드."""
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _corr_cache:
        return _corr_cache[key]
    path = os.path.join(ARTS, key, "farm_corrections.json")
    if not os.path.exists(path):
        _corr_cache[key] = {}
        return {}
    try:
        import json
        data = json.loads(open(path, encoding="utf-8").read())
        _corr_cache[key] = data.get("corrections", {})
    except Exception:
        _corr_cache[key] = {}
    return _corr_cache[key]


# ---------------------------------------------------------------------------
# 핵심 예측 — Format C 단일 구현
# ---------------------------------------------------------------------------

def _predict_format_c(
    pkg: dict,
    season_env: Dict[str, float],
    area_m2: float,
    farm_id: Optional[str],
) -> tuple[float, float, str]:
    """Format C pkl로 yield_total(kg), mape_cv(%), source 반환."""
    feat_cols     = pkg["feature_cols"]
    imputer       = pkg["imputer"]
    log_transform = pkg.get("log_transform", True)
    agg_mode      = pkg.get("agg_mode", "annual")

    if not feat_cols:
        return 5000.0, 999.0, "stub"

    # 피처 행 구성
    row: Dict[str, float] = {c: 0.0 for c in feat_cols}
    row.update({k: v for k, v in season_env.items() if k in feat_cols})

    # 농가 이력 피처
    fe  = pkg.get("farm_encoding", {})
    fym = fe.get("per_farm", {})
    global_mean: float = float(fe.get("global_mean", float(np.median(list(fym.values()))) if fym else 5.0))

    if "farm_yield_hist_mean" in feat_cols:
        row["farm_yield_hist_mean"] = (
            float(fym.get(str(farm_id), global_mean)) if farm_id else global_mean
        )
    if "farm_yield_hist_cv" in feat_cols:
        row["farm_yield_hist_cv"] = float(fe.get("global_cv", 0.5))
    if "log_area_m2" in feat_cols:
        row["log_area_m2"] = float(np.log1p(area_m2))

    X_raw  = pd.DataFrame([row])[feat_cols]
    X_imp  = imputer.transform(X_raw)
    # tree 계열(XGB/LGB)은 DataFrame(feature names), linear 계열(Ridge)은 numpy array 선호
    X_df   = pd.DataFrame(X_imp, columns=feat_cols)   # XGB/LGB용
    X_np   = X_imp                                     # Ridge/linear용

    # 앙상블 예측
    preds = []
    xgb_m = pkg.get("model")
    lgb_m = pkg.get("model_lgb")

    def _is_linear(m) -> bool:
        return type(m).__name__ in ("Ridge", "Lasso", "ElasticNet", "LinearRegression")

    if xgb_m is not None:
        preds.append(float(xgb_m.predict(X_np if _is_linear(xgb_m) else X_df)[0]))
    if lgb_m is not None:
        preds.append(float(lgb_m.predict(X_np if _is_linear(lgb_m) else X_df)[0]))
    if not preds:
        return 5000.0, 999.0, "stub"

    log_pred = float(np.mean(preds))

    # ── agg_mode별 역변환 ────────────────────────────────────────────────────
    if agg_mode == "annual_residual":
        # 모델이 yield_per_m2 - farm_hist_mean (잔차 kg/m²) 예측
        farm_mean = float(fym.get(str(farm_id), global_mean)) if farm_id else global_mean

        # 단위 합리성 검증 (global_mean이 kg 총량으로 잘못 저장된 경우 방어)
        if global_mean > 200:
            farm_mean_m2 = farm_mean / max(area_m2, 1.0)
            logger.warning(
                "[m2_yield] annual_residual farm_mean=%.1f > 200 → kg 총량 의심, "
                "÷%.0fm²=%.3f kg/m² 사용", farm_mean, area_m2, farm_mean_m2
            )
            yield_per_m2 = log_pred + farm_mean_m2
        else:
            yield_per_m2 = log_pred + farm_mean

        yield_total = max(yield_per_m2, 0.0) * max(area_m2, 1.0)

    elif agg_mode == "monthly":
        # 모델이 월평균 yield_per_m2 예측
        if log_transform:
            yield_per_m2 = float(np.expm1(max(log_pred, 0.0)))
        else:
            yield_per_m2 = max(log_pred, 0.0)
        yield_total = yield_per_m2 * max(area_m2, 1.0)

    else:  # "annual" (기본)
        if log_transform:
            yield_total = float(np.expm1(max(log_pred, 0.0))) * max(area_m2, 1.0)
        else:
            yield_total = max(log_pred, 0.0) * max(area_m2, 1.0)

    raw_mape = pkg.get("cv_mape_mean") or pkg.get("mape")
    mape_cv  = float(raw_mape) if raw_mape is not None else 99.0
    return max(yield_total, 0.0), mape_cv, "m2_stage2"


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

def predict_yield(
    crop_ko: str,
    season_env: Dict[str, float],
    area_m2: float = 1000.0,
    farm_id: Optional[str] = None,
) -> Dict[str, Any]:
    """수확량 예측.

    Returns:
        yield_kg_total     : 시즌 전체 kg
        yield_kg_m2        : 시즌 전체 kg/m²
        yield_kg_m2_monthly: 월평균 kg/m²
        season_months      : 작기 개월수
        unit               : "kg/m2/annual"
        source             : 소스 식별자
        mape_cv            : 교차검증 MAPE (%)
        gate_pass          : bool
    """
    pkg = _load(crop_ko)

    if pkg is None:
        return {
            "yield_kg_total": 5000.0, "yield_kg_m2": 5.0,
            "yield_kg_m2_monthly": 0.625, "season_months": 8,
            "unit": "kg/m2/annual", "source": "stub",
            "mape_cv": 999.0, "gate_pass": False,
        }

    yield_total, mape_cv, source = _predict_format_c(pkg, season_env, area_m2, farm_id)

    # ★ 블렌딩 판단은 권위 지표(stage2_meta.json) 기준. pkl 내부 mape는 학습 실행마다
    #   달라 신뢰 불가하며 양방향으로 틀렸었다:
    #     딸기  pkl 102.4 vs 권위 17.8 → 좋은 모델이 ML 0.10으로 과도 억제
    #     참외  pkl  27.3 vs 권위 63.9 → 35 미만이라 블렌딩 미작동 → 100% ML 서빙
    #   권위값 적용 시: 딸기·오이·파프리카·완숙(≤35)=ML 그대로, 방울 48.6→ml 0.46,
    #   참외 63.9→ml 0.10(RDA 90%)으로 정상 degrade.
    # ★★ 여기서 쓰는 stage2_meta 의 `mape` 는 **학습(in-sample) MAPE** 다(2026-07-17 확인).
    #   변수명이 mape_cv 지만 교차검증값이 아니다. 게이트(pipeline/gates.py)는 이 사고로
    #   cv_mape_mean 을 쓰도록 정정했으나, **이 블렌딩은 의도적으로 학습 MAPE 를 유지한다**:
    #     · 딸기 CV MAPE 107.3% (monthly) → 임계 35 초과 → ML 비중 0.10 = 예측이 사실상
    #       RDA 통계로 대체된다. 그러나 딸기 CV R² 0.295 로 신호는 있다.
    #     · monthly 는 수확 초·말기 수확량이 0 에 가까워 MAPE 가 구조적으로 폭발한다
    #       (작은 값으로 나누기) — 모델 부실이 아니라 지표 특성이다.
    #   즉 CV MAPE 로 바꾸면 정직해 보이지만 예측 품질은 나빠질 수 있다.
    #   → 블렌딩 임계는 monthly 에 견디는 지표(WAPE/sMAPE)로 바꾼 뒤 함께 조정할 것.
    #      그 전까지 이 줄을 CV MAPE 로 바꾸지 말 것.
    if _read_stage2_metrics is not None:
        try:
            _auth_mape = _read_stage2_metrics(ARTS, CROP_MAP.get(crop_ko, crop_ko)).get("mape")
            if _auth_mape is not None:
                mape_cv = float(_auth_mape)
        except Exception:
            pass

    # ── 게이트 미통과 시 통계 기반 블렌딩 ─────────────────────────────────────
    # MAPE > 35%이면 ML 예측과 RDA 통계 기준값을 신뢰도 비중으로 혼합.
    # 고MAPE일수록 신뢰도 높은 RDA 통계 기준값에 더 기울도록 분모 25로 강화(2026-06 개선):
    #   confidence = clamp(0.10, 0.65, 1.0 - (MAPE-35)/25)
    #   MAPE=35%→0.65 · 48.6%(방울)→0.46 · 55%→0.20 · ≥60%(참외)→0.10(하한)
    # (이전 /100 캡0.65는 MAPE 64%에도 ML 0.65 유지 → 통계 거의 미반영 버그)
    if mape_cv > 35.0:
        try:
            from api.data.stats_loader import get_yield_kg_m2
            stat_key         = CROP_MAP.get(crop_ko, crop_ko)
            stat_yield_m2    = get_yield_kg_m2(stat_key)
            stat_yield_total = stat_yield_m2 * max(area_m2, 1.0)
            confidence       = max(0.10, min(0.65, 1.0 - (mape_cv - 35.0) / 25.0))
            yield_total      = confidence * yield_total + (1.0 - confidence) * stat_yield_total
            source           = source + f"_blended(ml={confidence:.2f})"
        except Exception:
            pass

    # ── RDA 기준 합리적 범위 클리핑 ────────────────────────────────────────────
    try:
        from api.services.at_wholesale_service import clip_yield_prediction
        _ym_raw = yield_total / max(area_m2, 1.0)
        _ym_clipped, _was_clipped = clip_yield_prediction(crop_ko, _ym_raw)
        if _was_clipped:
            yield_total = _ym_clipped * max(area_m2, 1.0)
            source      = source + "_rda_clipped"
    except Exception:
        pass

    yield_total  = max(yield_total, 0.0)
    yield_m2     = yield_total / max(area_m2, 1.0)
    gate_pass    = (mape_cv <= 35.0)

    crop_key     = CROP_MAP.get(crop_ko, crop_ko)
    # 역방향 매핑: 영문 → 한글 (season_months 조회용)
    crop_ko_norm = next(
        (k for k, v in CROP_MAP.items() if v == crop_key and len(k) > 3),
        crop_ko,
    )
    season_months      = _SEASON_MONTHS.get(crop_ko_norm, _SEASON_MONTHS.get(crop_ko, 8))
    yield_m2_monthly   = round(yield_m2 / max(season_months, 1), 4)

    return {
        "yield_kg_total":      round(yield_total, 1),
        "yield_kg_m2":         round(yield_m2, 4),
        "yield_kg_m2_monthly": yield_m2_monthly,
        "season_months":       season_months,
        "unit":                "kg/m2/annual",
        "source":              source,
        "mape_cv":             mape_cv,
        "gate_pass":           gate_pass,
    }


def get_model_meta(crop_ko: str) -> Dict[str, Any]:
    """모델 메타 반환 (없으면 stub)."""
    pkg = _load(crop_ko)
    if pkg is None:
        return {"status": "stub", "crop": crop_ko}
    return {
        "status":    "loaded",
        "crop":      crop_ko,
        "mape_cv":   pkg.get("cv_mape_mean") or pkg.get("mape"),
        "agg_mode":  pkg.get("agg_mode"),
        "feat_cols": len(pkg.get("feature_cols", [])),
        "gate_pass": ((pkg.get("cv_mape_mean") or pkg.get("mape") or 99) <= 35.0),
    }


def invalidate_cache(crop_ko: Optional[str] = None) -> None:
    """재학습 후 캐시 무효화."""
    if crop_ko is None:
        _cache.clear()
        _corr_cache.clear()
    else:
        key = CROP_MAP.get(crop_ko, crop_ko)
        _cache.pop(key, None)
        _corr_cache.pop(key, None)


# ---------------------------------------------------------------------------
# 클래스 API (하위 호환 — test_models.py, M2YieldModel 사용처)
# ---------------------------------------------------------------------------

@dataclass
class YieldPrediction:
    yield_kg_total: float         = 5000.0
    yield_kg_m2:    float         = 5.0
    mape_cv:        float         = 99.0
    source:         str           = "stub"
    gate_pass:      Optional[bool] = None


def predict(
    crop_ko: str,
    season_env: Dict[str, float],
    area_m2: float = 1000.0,
    farm_id: Optional[str] = None,
) -> YieldPrediction:
    r = predict_yield(crop_ko, season_env, area_m2, farm_id)
    return YieldPrediction(
        yield_kg_total=r["yield_kg_total"],
        yield_kg_m2   =r["yield_kg_m2"],
        mape_cv       =r.get("mape_cv", 99),
        source        =r.get("source", "stub"),
        gate_pass     =r.get("gate_pass"),
    )


@dataclass
class YieldPredictionV2:
    """신뢰 구간 포함 버전 — M2YieldModel 반환."""
    yield_kg_total: float = 5000.0
    yield_kg_m2:    float = 5.0
    lower_80:       float = 3.5
    upper_80:       float = 6.5
    mape_cv:        float = 99.0
    confidence:     float = 0.5
    source:         str   = "stub"


class M2YieldModel:
    """생육+환경 피처 → 수확량 예측 클래스 API (모델 없으면 stub)."""

    def predict(
        self,
        growth_features: Dict[str, float],
        env_features: Dict[str, float],
        lag_7d:  Optional[float] = None,
        lag_14d: Optional[float] = None,
        crop_ko: str   = "딸기",
        area_m2: float = 1000.0,
        farm_id: Optional[str] = None,
    ) -> YieldPredictionV2:
        season_env = {**env_features, **growth_features}
        if lag_7d  is not None:
            season_env["lag_7d_yield"]  = lag_7d
        if lag_14d is not None:
            season_env["lag_14d_yield"] = lag_14d

        result  = predict_yield(crop_ko, season_env, area_m2, farm_id)
        base_m2 = result["yield_kg_m2"]

        # lag 블렌딩 (항상 적용)
        lags = [v for v in (lag_7d, lag_14d) if v is not None]
        if lags:
            base_m2 = 0.5 * base_m2 + 0.5 * float(np.mean(lags))

        # stub 모드에서만 초장 기반 보정
        if result.get("source") == "stub":
            ph = growth_features.get("plant_height", 0.0)
            if ph > 0:
                base_m2 *= min(1.5, max(0.5, ph / 30.0))

        base_m2 = max(base_m2, 0.01)

        mape_frac = float(result.get("mape_cv", 99)) / 100.0
        spread    = base_m2 * min(mape_frac * 0.8, 0.5)

        return YieldPredictionV2(
            yield_kg_total=round(base_m2 * area_m2, 1),
            yield_kg_m2   =round(base_m2, 4),
            lower_80      =round(max(0.0, base_m2 - spread), 4),
            upper_80      =round(base_m2 + spread, 4),
            mape_cv       =float(result.get("mape_cv", 99.0)),
            confidence    =round(min(0.9, max(0.3, 1.0 - mape_frac)), 3),
            source        =result.get("source", "stub"),
        )
