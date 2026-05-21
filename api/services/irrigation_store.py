"""관수 데이터 영속화 서비스.

POST /irrigation → adapt_irrigation() 결과를 저장하고
GET  /irrigation/analysis 에서 조회할 수 있도록 합니다.

저장 우선순위: PostgreSQL env_measurements → JSON 폴백 (api/data/irrigation_logs/)
조회 우선순위: PostgreSQL → JSON 폴백

JSON 파일 형식:
    api/data/irrigation_logs/{farm_id}.json
    {
        "2026-05-20": {
            "wc_mean": 93.3,
            "wc_max":  98.7,
            "wc_min":  83.3,
            "dr_pct_mean": 31.7,
            "ec_drain": 2.5,
            "supply_total": 1050.0,
            "irr_count": 3.0,
            "nl_pct": 8.8,
            "recorded_at": "2026-05-20T12:34:56+00:00"
        },
        ...
    }
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT      = Path(__file__).resolve().parents[2]
_LOG_DIR   = _ROOT / "api" / "data" / "irrigation_logs"
_lock      = Lock()

# 관수 canonical 변수 목록 (irrigation_adapter.py 산출값)
_IRR_VARS = ["wc_mean", "wc_max", "wc_min", "dr_pct_mean",
             "ec_drain", "supply_total", "irr_count", "nl_pct"]

# 각 변수의 정상 범위 (판정용)
_NORMAL_RANGES = {
    "wc_mean":     (60.0, 95.0),   # 함수율 60–95%
    "dr_pct_mean": (20.0, 40.0),   # 배액률 20–40%
    "ec_drain":    (2.0,  4.5),    # 배액 EC 2.0–4.5 dS/m
    "nl_pct":      (0.0,  15.0),   # 야간소실률 0–15%
}

# ── JSON 파일 핸들러 ──────────────────────────────────────────────────────────

def _log_path(farm_id: str) -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR / f"{farm_id}.json"


def _load_log(farm_id: str) -> dict:
    p = _log_path(farm_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[irrigation_store] JSON 읽기 실패 farm=%s: %s", farm_id, e)
    return {}


def _save_log(farm_id: str, data: dict) -> None:
    try:
        _log_path(farm_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("[irrigation_store] JSON 저장 실패 farm=%s: %s", farm_id, e)


# ── DB 저장/조회 ─────────────────────────────────────────────────────────────

def _db_save(farm_id: str, date_str: str, summary: dict[str, float]) -> bool:
    """env_measurements 테이블에 관수 canonical 레코드 저장."""
    try:
        from api.services.db import get_connection  # type: ignore
        ts = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                for var, val in summary.items():
                    if var in _IRR_VARS and val is not None:
                        cur.execute(
                            """INSERT INTO env_measurements
                               (farm_id, ts, variable, value, source)
                               VALUES (%s, %s, %s, %s, 'irrigation_p4')
                               ON CONFLICT (farm_id, ts, variable) DO UPDATE
                               SET value = EXCLUDED.value""",
                            (farm_id, ts, var, float(val))
                        )
            conn.commit()
        return True
    except Exception:
        return False


def _db_query(
    farm_id: str,
    start: date,
    end: date,
) -> dict[str, dict[str, float]]:
    """env_measurements에서 관수 변수를 일별 dict로 반환.

    Returns:
        {"2026-05-20": {"wc_mean": 93.3, ...}, ...}
    """
    try:
        from api.services.db import get_connection  # type: ignore
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT ts::date AS day, variable, value
                       FROM env_measurements
                       WHERE farm_id = %s
                         AND variable = ANY(%s)
                         AND ts::date BETWEEN %s AND %s
                         AND source = 'irrigation_p4'
                       ORDER BY day, variable""",
                    (farm_id, _IRR_VARS, start.isoformat(), end.isoformat())
                )
                rows = cur.fetchall()
        result: dict[str, dict] = {}
        for day, var, val in rows:
            key = str(day)
            result.setdefault(key, {})[var] = float(val)
        return result
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def save_irrigation_day(
    farm_id: str,
    date_str: str,
    summary: dict[str, float],
) -> None:
    """관수 1일치 canonical 집계값을 저장.

    Args:
        farm_id:   농장 ID
        date_str:  날짜 문자열 (YYYY-MM-DD)
        summary:   {canonical_name: value} dict (adapt_irrigation 출력)
    """
    # DB 저장 시도
    db_ok = _db_save(farm_id, date_str, summary)

    # JSON 폴백 (항상 저장 — DB 실패 시 유일한 저장소)
    with _lock:
        data = _load_log(farm_id)
        data[date_str] = {
            **{k: v for k, v in summary.items() if k in _IRR_VARS},
            "recorded_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        # 최근 90일만 보관
        if len(data) > 90:
            for old_key in sorted(data.keys())[:-90]:
                del data[old_key]
        _save_log(farm_id, data)

    logger.info(
        "[irrigation_store] 저장 farm=%s date=%s db=%s vars=%d",
        farm_id, date_str, "ok" if db_ok else "json폴백", len(summary),
    )


def get_irrigation_analysis(
    farm_id: str,
    days: int = 7,
) -> dict:
    """최근 N일 관수 분석 결과 반환.

    Returns:
        {
            "farm_id":   str,
            "days":      int,
            "records":   [ {date, wc_mean, dr_pct_mean, ec_drain, ...}, ... ],
            "summary":   {var: {avg, min, max, latest, status}},
            "alerts":    [ {var, value, message_ko, severity}, ... ],
            "data_days": int,   # 실제 데이터가 있는 날 수
        }
    """
    end   = date.today()
    start = end - timedelta(days=days - 1)

    # DB 우선 조회
    daily_data = _db_query(farm_id, start, end)

    # DB 결과 없으면 JSON 폴백
    if not daily_data:
        with _lock:
            raw = _load_log(farm_id)
        for d_str, vals in raw.items():
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if start <= d <= end:
                daily_data[d_str] = {k: v for k, v in vals.items() if k != "recorded_at"}

    # 날짜 정렬된 레코드 리스트
    records = []
    for d_str in sorted(daily_data.keys()):
        rec = {"date": d_str, **daily_data[d_str]}
        records.append(rec)

    # 변수별 통계 집계
    var_values: dict[str, list[float]] = {v: [] for v in _IRR_VARS}
    for rec in records:
        for var in _IRR_VARS:
            if var in rec and rec[var] is not None:
                var_values[var].append(float(rec[var]))

    summary: dict[str, dict] = {}
    for var in _IRR_VARS:
        vals = var_values[var]
        if not vals:
            continue
        lo, hi = _NORMAL_RANGES.get(var, (None, None))
        latest = vals[-1]
        if lo is not None and hi is not None:
            status = "normal" if lo <= latest <= hi else (
                "high" if latest > hi else "low"
            )
        else:
            status = "normal"
        summary[var] = {
            "avg":    round(sum(vals) / len(vals), 2),
            "min":    round(min(vals), 2),
            "max":    round(max(vals), 2),
            "latest": round(latest, 2),
            "unit":   _var_unit(var),
            "label_ko": _var_label(var),
            "status": status,
        }

    # 이상 알림
    alerts = []
    for var, stat in summary.items():
        if stat["status"] != "normal":
            lo, hi = _NORMAL_RANGES.get(var, (None, None))
            if stat["status"] == "high":
                msg = f"{stat['label_ko']} 과다 ({stat['latest']}{stat['unit']}, 기준 ≤{hi})"
            else:
                msg = f"{stat['label_ko']} 부족 ({stat['latest']}{stat['unit']}, 기준 ≥{lo})"
            alerts.append({
                "variable":   var,
                "label_ko":   stat["label_ko"],
                "value":      stat["latest"],
                "unit":       stat["unit"],
                "status":     stat["status"],
                "message_ko": msg,
                "severity":   "major" if stat["status"] == "high" else "minor",
            })

    return {
        "farm_id":   farm_id,
        "days":      days,
        "start":     start.isoformat(),
        "end":       end.isoformat(),
        "data_days": len(records),
        "records":   records,
        "summary":   summary,
        "alerts":    alerts,
    }


def _var_unit(var: str) -> str:
    return {
        "wc_mean":     "%",
        "wc_max":      "%",
        "wc_min":      "%",
        "dr_pct_mean": "%",
        "ec_drain":    "dS/m",
        "supply_total":"ml",
        "irr_count":   "회",
        "nl_pct":      "%",
    }.get(var, "")


def _var_label(var: str) -> str:
    return {
        "wc_mean":     "함수율(평균)",
        "wc_max":      "함수율(최대)",
        "wc_min":      "함수율(최소)",
        "dr_pct_mean": "배액률",
        "ec_drain":    "배액 EC",
        "supply_total":"총 공급량",
        "irr_count":   "관수 횟수",
        "nl_pct":      "야간소실률",
    }.get(var, var)
