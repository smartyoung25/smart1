"""M2 수확량 예측 v2 – log_yield / log_yield_ratio 자동 감지 + 농가별 bias correction"""
import logging
import os, pickle, json
import numpy as np, pandas as pd
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ARTS = os.path.join(os.path.dirname(__file__), "artifacts")
CROP_MAP = {
    "딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
    "참외":"melon","파프리카":"paprika",
    "strawberry":"strawberry","cherry_tomato":"cherry_tomato",
    "tomato":"tomato","melon":"melon","paprika":"paprika",
}

# 작기 개월수 — 연간 예측값을 월별로 환산할 때 사용
# predict_yield()는 연간(kg/m²/season) 값을 반환함을 명시
_SEASON_MONTHS: dict[str, int] = {
    "딸기": 6, "방울토마토": 8, "완숙토마토": 8,
    "참외": 4, "파프리카": 10,
}
_cache: Dict[str, Any] = {}
_corr_cache: Dict[str, Any] = {}

def _load(crop_ko: str):
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _cache: return _cache[key]
    pkl = os.path.join(ARTS, key, "m2_yield_model.pkl")
    if not os.path.exists(pkl): return None
    with open(pkl, "rb") as f: pkg = pickle.load(f)
    _cache[key] = pkg
    return pkg

def _load_corrections(crop_ko: str) -> Dict[str, Any]:
    """Load per-farm bias correction factors. Returns empty dict if not found."""
    key = CROP_MAP.get(crop_ko, crop_ko)
    if key in _corr_cache: return _corr_cache[key]
    path = os.path.join(ARTS, key, "farm_corrections.json")
    if not os.path.exists(path):
        _corr_cache[key] = {}
        return {}
    try:
        data = json.loads(open(path, encoding="utf-8").read())
        _corr_cache[key] = data.get("corrections", {})
    except Exception:
        _corr_cache[key] = {}
    return _corr_cache[key]

def predict_yield(crop_ko: str, season_env: Dict[str, float],
                  area_m2: float = 1000.0,
                  farm_id: Optional[str] = None) -> Dict[str, float]:
    pkg = _load(crop_ko)
    if pkg is None:
        return {"yield_kg_total":5000.0,"yield_kg_m2":5.0,"source":"stub",
                "mape_cv":999.0,"gate_pass":False}

    # ── 포맷 감지 ─────────────────────────────────────────────────────────────
    # 포맷 A (train_stage2_yield.py): feat_cols, feat_median, target, farm_yield_mean
    # 포맷 B (continuous_learning_dag retrain_m2): features, log_transform, cv_mape
    if "feat_cols" in pkg:
        # ── 포맷 A ────────────────────────────────────────────────────────────
        feat_cols = pkg["feat_cols"]
        med       = pkg.get("feat_median", {})
        tgt       = pkg.get("target", "log_yield")

        row = {c: med.get(c, 0.0) for c in feat_cols}
        row.update(season_env)
        if "log_area" in feat_cols:
            row["log_area"] = float(np.log1p(area_m2))

        farm_mean_map = pkg.get("farm_yield_mean", {})
        if "farm_yield_mean" in feat_cols:
            if farm_id and farm_id in farm_mean_map:
                row["farm_yield_mean"] = float(farm_mean_map[farm_id])
            else:
                row["farm_yield_mean"] = (
                    float(np.median(list(farm_mean_map.values())))
                    if farm_mean_map else 5000.0
                )
        if "farm_yield_std" in feat_cols:
            row["farm_yield_std"] = (
                float(np.std(list(farm_mean_map.values())))
                if farm_mean_map else 2000.0
            )
        if "farm_n" in feat_cols:
            row["farm_n"] = 3.0

        X = pd.DataFrame([row])[feat_cols]
        px = pkg["xgb"].predict(X)[0]
        pl = pkg["lgb"].predict(X)[0]
        log_pred = 0.5 * (px + pl)

        if tgt == "log_yield_ratio":
            # log_yield_ratio = log(yield / farm_mean) → 역변환: yield = exp(pred) × farm_mean
            # np.expm1(x) = exp(x)-1 이므로 여기서는 np.exp() 사용
            farm_mean  = row.get("farm_yield_mean", 5000.0)
            yield_total = float(np.exp(log_pred) * farm_mean)
        else:
            yield_total = float(np.expm1(max(log_pred, 0)))

        mape_cv = pkg.get("mape", 99)
        source  = "m2_model_v2"

    elif "feature_cols" in pkg and "imputer" in pkg:
        # ── 포맷 C (train_stage2_yield.py) — imputer + model/model_lgb ─────────
        feat_cols     = pkg["feature_cols"]
        imputer       = pkg["imputer"]
        log_transform = pkg.get("log_transform", True)

        if not feat_cols:
            return {"yield_kg_total": 5000.0, "yield_kg_m2": 5.0, "source": "stub",
                    "mape_cv": 999.0, "gate_pass": False}

        # 피처 행 구성: 0으로 초기화 (imputer가 훈련 중앙값으로 채움)
        row = {c: 0.0 for c in feat_cols}
        row.update(season_env)   # 환경값 오버라이드

        # 농가 이력 피처 처리 (farm_encoding에서 조회)
        fe  = pkg.get("farm_encoding", {})
        fym = fe.get("per_farm", {})
        if "farm_yield_hist_mean" in feat_cols:
            if farm_id and str(farm_id) in fym:
                row["farm_yield_hist_mean"] = float(fym[str(farm_id)])
            else:
                row["farm_yield_hist_mean"] = float(
                    fe.get("global_mean",
                           float(np.median(list(fym.values()))) if fym else 5.0)
                )
        if "farm_yield_hist_cv" in feat_cols:
            row["farm_yield_hist_cv"] = float(fe.get("global_cv", 0.5))
        if "log_area_m2" in feat_cols:
            row["log_area_m2"] = float(np.log1p(area_m2))

        # imputer.transform: 0 패딩된 피처 → 훈련 중앙값으로 대체
        X_raw = pd.DataFrame([row])[feat_cols]
        X = imputer.transform(X_raw)

        preds = []
        xgb_m = pkg.get("model")
        lgb_m = pkg.get("model_lgb")
        if xgb_m is not None:
            preds.append(float(xgb_m.predict(X)[0]))
        if lgb_m is not None:
            preds.append(float(lgb_m.predict(X)[0]))
        if not preds:
            return {"yield_kg_total": 5000.0, "yield_kg_m2": 5.0, "source": "stub",
                    "mape_cv": 999.0, "gate_pass": False}

        log_pred = float(np.mean(preds))
        agg_mode = pkg.get("agg_mode", "annual")

        if agg_mode == "annual_residual":
            # 모델이 yield_residual(= yield_per_m2 - farm_hist_mean)을 예측.
            # farm_hist_mean 단위: kg/m²/년 (stage2_yield.pkl farm_encoding 기준)
            # 실제 수확량 = residual(kg/m²) + farm_hist_mean(kg/m²) = kg/m²/년
            farm_mean = float(
                fym.get(str(farm_id), fe.get("global_mean", 5.0))
                if farm_id and str(farm_id) in fym
                else fe.get("global_mean", float(np.median(list(fym.values()))) if fym else 5.0)
            )
            yield_per_m2 = log_pred + farm_mean   # 잔차(kg/m²) + baseline(kg/m²)

            # 단위 합리성 검증: 물리적으로 불가능한 값 클리핑
            # (farm_mean이 kg 총량으로 잘못 저장된 경우 방어)
            _global_mean_check = fe.get("global_mean", 5.0)
            if _global_mean_check > 200:
                # global_mean > 200이면 kg/m²가 아닌 kg 총량 단위로 저장된 것으로 판단
                # 면적으로 나눠 kg/m² 환산 후 잔차 더하기
                farm_mean_m2 = farm_mean / max(area_m2, 1.0)
                yield_per_m2 = log_pred + farm_mean_m2
                logger.warning(
                    "[m2_yield] annual_residual farm_mean=%.1f > 200 → kg 총량 의심, "
                    "÷%.0fm²=%.3f kg/m² 사용", farm_mean, area_m2, farm_mean_m2
                )
            yield_total  = max(yield_per_m2, 0) * max(area_m2, 1)
        elif log_transform:
            # 모델이 log1p(yield_per_m2)를 예측 → expm1 후 area_m2 곱
            yield_total = float(np.expm1(max(log_pred, 0))) * max(area_m2, 1)
        else:
            yield_total = max(log_pred, 0) * max(area_m2, 1)

        _raw_mape = pkg.get("cv_mape_mean") or pkg.get("mape")
        mape_cv = float(_raw_mape) if _raw_mape is not None else 99.0
        source  = "m2_stage2"

    else:
        # ── 포맷 B (DAG retrain_m2) ───────────────────────────────────────────
        feat_cols     = pkg.get("features", [])
        log_transform = pkg.get("log_transform", True)

        if not feat_cols:
            return {"yield_kg_total": 5000.0, "yield_kg_m2": 5.0, "source": "stub",
                    "mape_cv": 999.0, "gate_pass": False}

        # 누락 피처는 0으로 패딩
        row = {c: 0.0 for c in feat_cols}
        row.update(season_env)

        X = pd.DataFrame([row])[feat_cols]
        preds = []
        if pkg.get("xgb") is not None:
            preds.append(pkg["xgb"].predict(X)[0])
        if pkg.get("lgb") is not None:
            preds.append(pkg["lgb"].predict(X)[0])
        if not preds:
            return {"yield_kg_total": 5000.0, "yield_kg_m2": 5.0, "source": "stub",
                    "mape_cv": 999.0, "gate_pass": False}

        raw_pred = float(np.mean(preds))
        if log_transform:
            yield_total = float(np.expm1(max(raw_pred, 0))) * max(area_m2, 1)
        else:
            yield_total = max(raw_pred, 0) * max(area_m2, 1)

        mape_cv = pkg.get("cv_mape", 99)
        source  = "m2_dag_retrain"

    yield_total = max(yield_total, 0)

    # ── 게이트 미통과 시 통계 기반 블렌딩 ─────────────────────────────────────
    # gate_pass=False 이고 MAPE > 35% 이면 ML 예측과 통계 기준값을 신뢰도 비중으로 혼합.
    # deployment_gate.py STAGE2_MAPE threshold=35.0과 동기화.
    # 신뢰도 공식: confidence = max(0, 1.0 - (MAPE - 35) / 100)
    #   MAPE=35% → confidence=0.65  (ML 65% + stats 35%)
    #   MAPE=70% → confidence=0.30  (ML 30% + stats 70%)
    #   MAPE=100%→ confidence=0.00  (stats 100%)
    gate_pass = pkg.get("gate_pass", True) if pkg else True
    # MAPE > 35% 이면 gate_pass 필드 값에 무관하게 통계 기반 블렌딩 적용
    # (학습 당시 저장된 gate_pass 가 현재 STAGE2_MAPE≤35% 기준과 다를 수 있음)
    if mape_cv > 35.0:
        try:
            from api.data.stats_loader import get_yield_kg_m2
            stat_key         = CROP_MAP.get(crop_ko, crop_ko)
            stat_yield_m2    = get_yield_kg_m2(stat_key)          # kg/m²/작기
            stat_yield_total = stat_yield_m2 * max(area_m2, 1.0)
            confidence       = max(0.0, min(0.65, 1.0 - (mape_cv - 35.0) / 100.0))
            yield_total      = confidence * yield_total + (1.0 - confidence) * stat_yield_total
            source           = source + "_blended"
        except Exception:
            pass  # stats_loader 미설치 환경 등에서는 원래 값 유지

    yield_total = max(yield_total, 0)

    # ── RDA 기준 합리적 범위 클리핑 (과적합 이상값 방지) ─────────────────────────
    # 방울토마토 CV MAPE=231% 등 과적합 모델이 극단값을 예측할 때 RDA 기준으로 클리핑.
    # at_wholesale_service.py의 _KR_YIELD_BOUNDS (RDA 2021~2022) 기준 사용.
    try:
        from api.services.at_wholesale_service import clip_yield_prediction  # type: ignore
        _ym_raw = yield_total / max(area_m2, 1)
        _ym_clipped, _was_clipped = clip_yield_prediction(crop_ko, _ym_raw)
        if _was_clipped:
            yield_total = _ym_clipped * max(area_m2, 1)
            source = source + "_rda_clipped"
    except Exception:
        pass

    yield_total = max(yield_total, 0)
    yield_m2    = yield_total / max(area_m2, 1)

    # gate_pass: MAPE≤35% 기준으로 재평가 (deployment_gate.py 와 동기화)
    # stub 소스(모델 미탑재)일 때만 저장 값을 유지, 나머지는 MAPE 직접 평가
    _is_stub = (source == "stub")
    effective_gate_pass = gate_pass if _is_stub else (mape_cv <= 35.0)

    # 월별 수확량 환산 — 연간 예측값을 작기 개월수로 나눔
    # yield_kg_m2는 시즌 전체(연간) 값임을 명시
    crop_key = CROP_MAP.get(crop_ko, crop_ko)
    crop_ko_norm = next((k for k, v in CROP_MAP.items() if v == crop_key and len(k) > 3), crop_ko)
    season_months = _SEASON_MONTHS.get(crop_ko_norm, _SEASON_MONTHS.get(crop_ko, 8))
    yield_m2_monthly = round(yield_m2 / max(season_months, 1), 4)

    return {
        "yield_kg_total":         round(yield_total, 1),
        "yield_kg_m2":            round(yield_m2, 4),      # 연간(시즌) kg/m²
        "yield_kg_m2_monthly":    yield_m2_monthly,         # 월평균 kg/m²/월
        "season_months":          season_months,
        "unit":                   "kg/m2/annual",            # 단위 명시
        "source":                 source,
        "mape_cv":                mape_cv,
        "gate_pass":              effective_gate_pass,
    }

def get_model_meta(crop_ko: str) -> Dict:
    pkg = _load(crop_ko)
    if pkg is None: return {"status":"stub","crop":crop_ko}
    return {"mape": pkg.get("mape"), "train_r2": pkg.get("train_r2"),
            "gate_pass": pkg.get("gate_pass"), "crop": crop_ko,
            "target": pkg.get("target")}

@dataclass
class YieldPrediction:
    yield_kg_total: float = 5000.0
    yield_kg_m2:    float = 5.0
    mape_cv:        float = 99.0
    source:         str   = "stub"
    gate_pass:      Optional[bool] = None

def predict(crop_ko: str, season_env: Dict[str, float],
            area_m2: float = 1000.0,
            farm_id: Optional[str] = None) -> YieldPrediction:
    r = predict_yield(crop_ko, season_env, area_m2, farm_id)
    return YieldPrediction(
        yield_kg_total=r["yield_kg_total"],
        yield_kg_m2=r["yield_kg_m2"],
        mape_cv=r.get("mape_cv", 99),
        source=r.get("source", "stub"),
        gate_pass=r.get("gate_pass"))


# ── 클래스 API (test_models.py 호환) ──────────────────────────────────────────

@dataclass
class YieldPredictionV2:
    """신뢰 구간 + lag 피처 포함 버전 — M2YieldModel이 반환."""
    yield_kg_total: float = 5000.0
    yield_kg_m2:    float = 5.0
    lower_80:       float = 3.5    # 80% 예측 구간 하한
    upper_80:       float = 6.5    # 80% 예측 구간 상한
    mape_cv:        float = 99.0
    confidence:     float = 0.5
    source:         str   = "stub"


class M2YieldModel:
    """생육+환경 피처 → 수확량 예측 클래스 API (모델 없으면 수식 기반 stub)."""

    _DEFAULT_CROP  = "딸기"
    _BASE_YIELD_M2 = 5.0    # stub 기본 수확량 (kg/m²)

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
        # 피처 통합
        season_env = {**env_features, **growth_features}
        if lag_7d  is not None:
            season_env["lag_7d_yield"]  = lag_7d
        if lag_14d is not None:
            season_env["lag_14d_yield"] = lag_14d

        result = predict_yield(crop_ko, season_env, area_m2, farm_id)
        base_m2 = result["yield_kg_m2"]

        # lag 블렌딩: 항상 적용 (모델/stub 무관) — 과거 실적 이력과 블렌딩
        lags = [v for v in (lag_7d, lag_14d) if v is not None]
        if lags:
            lag_mean = float(np.mean(lags))
            base_m2  = 0.5 * base_m2 + 0.5 * lag_mean

        # stub 모드일 때만 초장 기반 성장 계수 보정 적용
        if result.get("source") == "stub":
            # 초장 기반 성장 계수 보정 (plant_height 30cm → 계수 1.0 기준)
            ph = growth_features.get("plant_height", 0.0)
            if ph > 0:
                base_m2 *= min(1.5, max(0.5, ph / 30.0))

        base_m2 = max(base_m2, 0.01)

        # 80% 예측 구간: MAPE를 spread 추정에 사용
        mape_frac = float(result.get("mape_cv", 99)) / 100.0
        spread    = base_m2 * min(mape_frac * 0.8, 0.5)
        lower_80  = max(0.0, base_m2 - spread)
        upper_80  = base_m2 + spread

        return YieldPredictionV2(
            yield_kg_total=round(base_m2 * area_m2, 1),
            yield_kg_m2=round(base_m2, 4),
            lower_80=round(lower_80, 4),
            upper_80=round(upper_80, 4),
            mape_cv=float(result.get("mape_cv", 99.0)),
            confidence=round(min(0.9, max(0.3, 1.0 - mape_frac)), 3),
            source=result.get("source", "stub"),
        )
