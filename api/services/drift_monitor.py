"""M2 예측 드리프트 모니터링 — 실측 수확량 vs M2 예측값 자동 비교

설계:
  - harvest_records JSON 파일을 읽어 실측 yield_kg_m2 수집
  - 각 레코드의 환경값으로 M2 predict_yield() 호출 → 예측값 생성
  - MAPE, 편향(bias), 추세(trend), 경보 수준 산출
  - PostgreSQL harvest_records 테이블도 시도 (JSON 폴백)

알림 기준:
  green  : MAPE ≤ 20%
  yellow : 20% < MAPE ≤ 35%
  red    : MAPE > 35%  또는 최근 5건 MAPE 급등 (>20%p 상승)
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# harvest JSON 저장 경로 (data_collection.py와 동일)
_HARVEST_DIR = Path("data/collected/harvest")

# 드리프트 계산에 사용할 최소 실측 건수
_MIN_SAMPLES = 3


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class DriftSample:
    """단일 실측-예측 쌍."""
    record_id:    str
    farm_id:      str
    crop_ko:      str
    harvest_date: str
    actual_m2:    float           # 실측 yield kg/m²
    predicted_m2: float           # M2 예측 yield kg/m²
    abs_pct_err:  float           # |actual - predicted| / actual × 100
    bias_pct:     float           # (predicted - actual) / actual × 100 (양수=과대예측)
    has_env:      bool = True     # season_avg_temp/humidity 실측값 존재 여부


@dataclass
class DriftStats:
    """작물별 드리프트 요약."""
    crop_ko:        str
    n_samples:      int
    mape:           float           # Mean Absolute Percentage Error (%)
    bias:           float           # 평균 편향 (%) — 양수=과대예측
    rmse_m2:        float           # kg/m² RMSE
    trend:          str             # "stable" | "improving" | "degrading"
    trend_delta:    float           # 최근 5건 MAPE − 전체 MAPE (%, 양수=악화)
    alert:          str             # "green" | "yellow" | "red"
    alert_reason:   str
    last_harvest:   Optional[str]   # 최신 수확일
    env_missing_pct: float = 0.0   # 환경값 누락 비율 (%) — 높을수록 imputer 기본값 의존
    gate_pass:      Optional[bool] = None   # M2 모델 gate 통과 여부
    samples:        List[DriftSample] = field(default_factory=list)
    computed_at:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["samples"] = [asdict(s) for s in self.samples]
        return d


# ---------------------------------------------------------------------------
# harvest 레코드 수집
# ---------------------------------------------------------------------------

def _load_harvest_json(crop_ko: Optional[str] = None,
                        farm_id: Optional[str] = None,
                        limit: int = 100) -> List[Dict[str, Any]]:
    """JSON 파일에서 harvest 레코드 로드. crop_ko / farm_id 필터 지원."""
    records: List[Dict[str, Any]] = []

    if not _HARVEST_DIR.exists():
        return records

    for fpath in _HARVEST_DIR.glob("*.json"):
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if crop_ko and data.get("crop_ko") != crop_ko:
                continue
            if farm_id and data.get("farm_id") != farm_id:
                continue
            if data.get("yield_kg_m2") is None:
                continue
            records.append(data)
        except Exception:
            pass

    # harvest_date 오름차순 (오래된 것 먼저 → 최근 limit건)
    #   recorded_at가 null이고 harvest_date 부재 시 None[:10] TypeError 방지
    records.sort(key=lambda r: (r.get("harvest_date") or r.get("recorded_at") or "")[:10])
    return records[-limit:]


def _load_harvest_db(crop_ko: Optional[str] = None,
                     farm_id: Optional[str] = None,
                     limit: int = 100) -> List[Dict[str, Any]]:
    """PostgreSQL harvest_records 테이블에서 로드. 실패 시 빈 리스트."""
    try:
        from api.services.persistence import _get_engine
        from sqlalchemy import text
        engine = _get_engine()
        if engine is None:
            return []

        filters = []
        params: Dict[str, Any] = {"limit": limit}
        if crop_ko:
            filters.append("crop_ko = :crop_ko")
            params["crop_ko"] = crop_ko
        if farm_id:
            filters.append("farm_id = :farm_id")
            params["farm_id"] = farm_id
        where = ("WHERE " + " AND ".join(filters)) if filters else ""

        with engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT payload FROM harvest_records
                    {where}
                    ORDER BY recorded_at DESC
                    LIMIT :limit
                """),
                params,
            ).fetchall()

        records = []
        for row in rows:
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if payload.get("yield_kg_m2") is None:
                continue
            records.append(payload)
        return records
    except Exception as e:
        logger.debug("[drift_monitor] DB 조회 실패 (JSON 폴백 사용): %s", e)
        return []


def _load_harvest_records(crop_ko: Optional[str] = None,
                           farm_id: Optional[str] = None,
                           limit: int = 100) -> List[Dict[str, Any]]:
    """DB 우선, 없으면 JSON 폴백."""
    db_recs = _load_harvest_db(crop_ko, farm_id, limit)
    if db_recs:
        return db_recs
    return _load_harvest_json(crop_ko, farm_id, limit)


# ---------------------------------------------------------------------------
# 핵심 계산
# ---------------------------------------------------------------------------

def _env_from_record(rec: Dict[str, Any]) -> Tuple[Dict[str, float], bool]:
    """harvest 레코드에서 M2 환경 피처 추출.

    Returns:
        (env_dict, has_env) — has_env=True 이면 실측 환경값 존재, False 이면 imputer 기본값 사용
    """
    env: Dict[str, float] = {}
    t = rec.get("season_avg_temp")
    h = rec.get("season_avg_humidity")
    if t is not None:
        env["temp_internal_mean"] = float(t)
    if h is not None:
        env["humidity_int_mean"] = float(h)
    has_env = t is not None or h is not None
    return env, has_env


def _compute_samples(records: List[Dict[str, Any]]) -> List[DriftSample]:
    """레코드 목록 → DriftSample 목록 (M2 predict 호출 포함)."""
    from models.m2_yield import predict_yield

    samples: List[DriftSample] = []
    for rec in records:
        actual_m2 = float(rec.get("yield_kg_m2", 0.0))
        if actual_m2 <= 0:
            continue

        crop_ko       = rec.get("crop_ko", "")
        farm_id       = rec.get("farm_id")
        area_m2       = float(rec.get("area_m2") or 1000.0)
        env_feat, has_env = _env_from_record(rec)

        try:
            pred = predict_yield(crop_ko, env_feat, area_m2=area_m2, farm_id=farm_id)
            # M2는 시즌 전체 kg/m² 반환 — 실측과 같은 단위
            pred_m2 = float(pred.get("yield_kg_m2", 0.0))
        except Exception as e:
            logger.debug("[drift_monitor] predict_yield 실패 %s: %s", crop_ko, e)
            continue

        if pred_m2 <= 0:
            continue

        abs_pct = abs(actual_m2 - pred_m2) / actual_m2 * 100.0
        bias    = (pred_m2 - actual_m2) / actual_m2 * 100.0

        samples.append(DriftSample(
            record_id    =rec.get("id", ""),
            farm_id      =farm_id or "",
            crop_ko      =crop_ko,
            harvest_date =str(rec.get("harvest_date") or rec.get("recorded_at", ""))[:10],
            actual_m2    =round(actual_m2, 4),
            predicted_m2 =round(pred_m2, 4),
            abs_pct_err  =round(abs_pct, 2),
            bias_pct     =round(bias, 2),
            has_env      =has_env,
        ))

    return samples


def _alert_level(mape: float, trend_delta: float) -> Tuple[str, str]:
    """(alert, reason) 결정."""
    if mape <= 20.0 and trend_delta <= 5.0:
        return "green", f"MAPE {mape:.1f}% — 예측 정확도 양호"
    if mape > 35.0:
        return "red", f"MAPE {mape:.1f}% — 재학습 권고 (기준: 35%)"
    if trend_delta > 20.0:
        return "red", f"최근 예측 오차 급등 (+{trend_delta:.1f}%p) — 환경 변화 또는 모델 드리프트"
    if mape > 20.0 or trend_delta > 10.0:
        return "yellow", f"MAPE {mape:.1f}% — 주의 필요 (기준: 20~35%)"
    return "green", f"MAPE {mape:.1f}% — 정상"


def _trend_label(trend_delta: float) -> str:
    if trend_delta > 5.0:
        return "degrading"
    if trend_delta < -5.0:
        return "improving"
    return "stable"


def _gate_pass_for(crop_ko: str) -> Optional[bool]:
    """M2 모델 gate_pass 조회 (실패 시 None)."""
    try:
        from models.m2_yield import get_model_meta
        return bool(get_model_meta(crop_ko).get("gate_pass"))
    except Exception:
        return None


def compute_drift(crop_ko: str,
                  farm_id: Optional[str] = None,
                  n_recent: int = 50) -> DriftStats:
    """단일 작물(+선택적 농장)의 드리프트 통계 산출."""
    records = _load_harvest_records(crop_ko, farm_id, limit=n_recent)
    samples = _compute_samples(records)
    gate_pass = _gate_pass_for(crop_ko)

    if len(samples) < _MIN_SAMPLES:
        return DriftStats(
            crop_ko         =crop_ko,
            n_samples       =len(samples),
            mape            =float("nan"),
            bias            =float("nan"),
            rmse_m2         =float("nan"),
            trend           ="unknown",
            trend_delta     =0.0,
            alert           ="yellow",
            alert_reason    =f"실측 데이터 부족 ({len(samples)}건 < {_MIN_SAMPLES}건)",
            last_harvest    =samples[-1].harvest_date if samples else None,
            env_missing_pct =0.0,
            gate_pass       =gate_pass,
            samples         =samples,
        )

    errs   = [s.abs_pct_err for s in samples]
    biases = [s.bias_pct    for s in samples]
    sq_err = [(s.actual_m2 - s.predicted_m2) ** 2 for s in samples]

    mape   = sum(errs) / len(errs)
    bias   = sum(biases) / len(biases)
    rmse   = math.sqrt(sum(sq_err) / len(sq_err))

    # 환경값 누락 비율
    env_missing_pct = round(
        sum(1 for s in samples if not s.has_env) / len(samples) * 100.0, 1
    )

    # 추세: 최근 5건 vs 전체 MAPE 차이
    recent5 = errs[-5:]
    recent_mape  = sum(recent5) / len(recent5)
    trend_delta  = recent_mape - mape      # 양수 = 악화
    trend        = _trend_label(trend_delta)
    alert, reason = _alert_level(mape, trend_delta)

    return DriftStats(
        crop_ko         =crop_ko,
        n_samples       =len(samples),
        mape            =round(mape, 2),
        bias            =round(bias, 2),
        rmse_m2         =round(rmse, 4),
        trend           =trend,
        trend_delta     =round(trend_delta, 2),
        alert           =alert,
        alert_reason    =reason,
        last_harvest    =samples[-1].harvest_date if samples else None,
        env_missing_pct =env_missing_pct,
        gate_pass       =gate_pass,
        samples         =samples,
    )


def compute_all_drift(farm_id: Optional[str] = None) -> Dict[str, DriftStats]:
    """전 작목 드리프트 통계 계산."""
    from models.crop_config import CROP_CONFIGS
    result: Dict[str, DriftStats] = {}
    for crop_ko in CROP_CONFIGS:
        try:
            result[crop_ko] = compute_drift(crop_ko, farm_id=farm_id)
        except Exception as e:
            logger.warning("[drift_monitor] %s 계산 실패: %s", crop_ko, e)
    return result


def summary_badge(stats: DriftStats) -> Dict[str, Any]:
    """대시보드 카드용 요약 dict."""
    def _f(v):  # ★ NaN → None — 저표본 NaN 이 기본 JSON 인코더서 'NaN'(파싱불가 JSON) 방출하던 문제
        return None if (isinstance(v, float) and v != v) else v
    return {
        "crop_ko":         stats.crop_ko,
        "n_samples":       stats.n_samples,
        "mape":            _f(stats.mape),
        "bias":            _f(stats.bias),
        "trend":           stats.trend,
        "trend_delta":     stats.trend_delta,
        "alert":           stats.alert,
        "alert_reason":    stats.alert_reason,
        "last_harvest":    stats.last_harvest,
        "env_missing_pct": stats.env_missing_pct,
        "gate_pass":       stats.gate_pass,
        "computed_at":     stats.computed_at,
    }
