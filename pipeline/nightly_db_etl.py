"""야간 DB → Parquet ETL 스크립트

TimescaleDB의 env_measurements / growth_measurements 테이블을 읽어
일별 집계(wide pivot) 후 env_daily.parquet / growth_daily.parquet 에 증분 추가.

Task Scheduler 설정:
  Execute : C:\tools\python311\python.exe
  Args    : -m pipeline.nightly_db_etl
  StartIn : C:\smart_farm

로그: C:\smart_farm\pipeline\logs\nightly_db_etl.log
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent                     # C:\smart_farm
ETL_DIR   = ROOT / "outputs" / "etl"
STATE_DIR = ROOT / "pipeline" / "state"
LOG_DIR   = ROOT / "pipeline" / "logs"
for d in [ETL_DIR, STATE_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

ENV_PARQUET    = ETL_DIR / "env_daily.parquet"
GROWTH_PARQUET = ETL_DIR / "growth_daily.parquet"
PROD_PARQUET   = ETL_DIR / "prod_daily.parquet"
STATE_FILE     = STATE_DIR / "new_rows_since_retrain.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "nightly_db_etl.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nightly_db_etl")

# crop_type 영어 → 한국어 (training scripts는 한국어로 필터링)
_CROP_EN_TO_KO: dict[str, str] = {
    "strawberry":     "딸기",
    "cherry_tomato":  "방울토마토",
    "tomato":         "완숙토마토",
    "melon":          "참외",
    "paprika":        "파프리카",
    "cucumber":       "오이",
    # 제주 주력 노지작물
    "citrus":         "감귤",
    "winter_radish":  "월동무",
    "carrot":         "당근",
    "cabbage":        "양배추",
}


# ── 환경 변수 / DB 연결 ──────────────────────────────────────────────────────────
def _get_db_url() -> str:
    # .env 로드
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                raw = line.split("=", 1)[1]
                # SQLAlchemy prefix → psycopg2 compatible
                return raw.replace("postgresql+pg8000://", "postgresql://") \
                           .replace("postgresql+psycopg2://", "postgresql://")
    return os.getenv("DATABASE_URL", "postgresql://smartfarm:smartfarm@127.0.0.1:5432/smartfarm")


def _get_last_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"new_env_rows": 0, "new_prod_rows": 0, "last_updated": None}


def _save_state(new_env: int, new_prod: int) -> None:
    state = _get_last_state()
    state["new_env_rows"]  = state.get("new_env_rows", 0)  + new_env
    state["new_prod_rows"] = state.get("new_prod_rows", 0) + new_prod
    state["last_updated"]  = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── env_measurements → env_daily.parquet ──────────────────────────────────────
def export_env(conn, since: str | None = None) -> int:
    """
    env_measurements (long) → wide daily pivot.
    컬럼: farm_id, crop, season, year, date, temp_internal_mean, humidity_int_mean, ...

    Args:
        since: 이 날짜 이후 데이터 강제 추출 (YYYY-MM-DD). None이면 parquet cutoff 자동 사용.
    """
    import pandas as pd

    log.info("env_measurements 읽는 중...")

    # 마지막 parquet 날짜 이후 데이터만 추출 (증분)
    if since:
        cutoff = since
        log.info("env: --since 강제 cutoff=%s", cutoff)
    else:
        cutoff = "1900-01-01"
        if ENV_PARQUET.exists():
            try:
                existing = pd.read_parquet(ENV_PARQUET, columns=["date"])
                if len(existing):
                    cutoff = existing["date"].max()
            except Exception:
                pass

    # DB-side CASE WHEN aggregation (avoids loading 600k rows into Python memory)
    query = f"""
        SELECT
            em.time::date                                      AS date,
            em.farm_id,
            f.crop_type                                        AS crop,
            EXTRACT(YEAR FROM em.time)::int                    AS year,
            '1'                                                AS season,
            AVG(CASE WHEN em.canonical_name = 'temp_internal' THEN em.value END) AS temp_internal_mean,
            MAX(CASE WHEN em.canonical_name = 'temp_internal' THEN em.value END) AS temp_internal_max,
            MIN(CASE WHEN em.canonical_name = 'temp_internal' THEN em.value END) AS temp_internal_min,
            AVG(CASE WHEN em.canonical_name = 'temp_external' THEN em.value END) AS temp_external_mean,
            AVG(CASE WHEN em.canonical_name = 'humidity_int'  THEN em.value END) AS humidity_int_mean,
            AVG(CASE WHEN em.canonical_name = 'co2_ppm'       THEN em.value END) AS co2_ppm_mean,
            AVG(CASE WHEN em.canonical_name = 'solar_rad'     THEN em.value END) AS solar_rad_mean,
            SUM(CASE WHEN em.canonical_name = 'solar_rad'     THEN em.value END) AS solar_rad_sum,
            AVG(CASE WHEN em.canonical_name = 'ec_dsm'        THEN em.value END) AS ec_dsm_mean,
            AVG(CASE WHEN em.canonical_name = 'soil_temp'     THEN em.value END) AS soil_temp_mean,
            -- 관수 피처 (irrigation_store 저장명 기준, ML prep_m1.py IRR_BASE와 동일)
            AVG(CASE WHEN em.canonical_name IN ('wc','wc_mean')       THEN em.value END) AS wc_mean,
            MAX(CASE WHEN em.canonical_name IN ('wc','wc_mean')       THEN em.value END) AS wc_max,
            MIN(CASE WHEN em.canonical_name IN ('wc','wc_min')        THEN em.value END) AS wc_min,
            AVG(CASE WHEN em.canonical_name IN ('dr_pct','dr_pct_mean') THEN em.value END) AS dr_pct_mean,
            AVG(CASE WHEN em.canonical_name = 'ec_drain'              THEN em.value END) AS ec_drain,
            SUM(CASE WHEN em.canonical_name = 'supply_total'          THEN em.value END) AS supply_total,
            SUM(CASE WHEN em.canonical_name = 'irr_count'             THEN em.value END) AS irr_count,
            AVG(CASE WHEN em.canonical_name = 'nl_pct'                THEN em.value END) AS nl_pct
        FROM env_measurements em
        JOIN farms f ON f.farm_id = em.farm_id
        WHERE em.time::date > '{cutoff}'
          AND (em.quality_tag IS NULL OR em.quality_tag NOT IN ('bad','ERROR'))
        GROUP BY em.time::date, em.farm_id, f.crop_type, EXTRACT(YEAR FROM em.time)
        ORDER BY em.farm_id, date
    """
    try:
        df = pd.read_sql(query, conn)
    except Exception as e:
        log.error("env_measurements 쿼리 오류: %s", e)
        return 0

    if df.empty:
        log.info("env: 신규 데이터 없음 (cutoff=%s)", cutoff)
        return 0

    # crop_type 영어 → 한국어 변환
    df["crop"] = df["crop"].map(lambda c: _CROP_EN_TO_KO.get(c, c))
    df["date"] = pd.to_datetime(df["date"])
    df["season"] = df["season"].astype(str)

    log.info("env 집계 행: %d (farm %d개)", len(df), df["farm_id"].nunique())

    # 기존 parquet 에 증분 추가
    new_rows = _merge_parquet(ENV_PARQUET, df, key_cols=["farm_id", "crop", "season", "date"])
    log.info("env_daily.parquet 신규 행: %d", new_rows)
    return new_rows


# ── growth_measurements → growth_daily.parquet ────────────────────────────────
def export_growth(conn) -> int:
    """
    growth_measurements (long) → wide daily pivot.
    컬럼: farm_id, crop, season, year, date, plant_height, leaf_count, ...
    """
    import pandas as pd

    log.info("growth_measurements 읽는 중...")

    cutoff = "1900-01-01"
    if GROWTH_PARQUET.exists():
        try:
            existing = pd.read_parquet(GROWTH_PARQUET, columns=["date"])
            if len(existing):
                cutoff = existing["date"].max()
        except Exception:
            pass

    query = f"""
        SELECT
            gm.time::date              AS date,
            gm.farm_id,
            gm.canonical_name,
            gm.value,
            gm.crop,
            EXTRACT(YEAR FROM gm.time)::int AS year,
            '1'                        AS season
        FROM growth_measurements gm
        WHERE gm.time::date > '{cutoff}'
        ORDER BY gm.farm_id, gm.time::date, gm.canonical_name
    """
    try:
        df = pd.read_sql(query, conn)
    except Exception as e:
        log.error("growth_measurements 쿼리 오류: %s", e)
        return 0

    if df.empty:
        log.info("growth: 신규 데이터 없음 (cutoff=%s)", cutoff)
        return 0

    log.info("growth 원시 행: %d", len(df))

    # 실제 DB canonical_names (variable_registry.sql 기준)
    GROWTH_COLS = {
        "plant_height":  "mean",
        "leaf_count":    "mean",
        "leaf_length":   "mean",
        "leaf_width":    "mean",
        "stem_diameter": "mean",
        "fruit_count":   "mean",
        "crown_diameter":"mean",
        "node_count":    "mean",
        # 생산량/매출은 sum (없으면 스킵)
        "yield_kg":      "sum",
        "revenue_krw":   "sum",
    }
    group_keys = ["farm_id", "crop", "season", "year", "date"]

    pivot_frames = []
    for col, stat in GROWTH_COLS.items():
        sub = df[df["canonical_name"] == col]
        if sub.empty:
            continue
        agg = sub.groupby(group_keys)["value"].agg(stat).reset_index()
        agg.rename(columns={"value": col}, inplace=True)
        pivot_frames.append(agg)

    if not pivot_frames:
        log.warning("growth pivot 결과 없음")
        return 0

    from functools import reduce
    wide = reduce(lambda a, b: a.merge(b, on=group_keys, how="outer"), pivot_frames)
    wide["date"] = pd.to_datetime(wide["date"])

    # prod_daily.parquet 도 yield/revenue 포함 (M2 학습 호환)
    prod_cols = [c for c in ["yield_kg", "revenue_krw"] if c in wide.columns]
    if prod_cols:
        prod = wide[group_keys + prod_cols].copy()
        _merge_parquet(PROD_PARQUET, prod, key_cols=["farm_id", "crop", "season", "date"])

    new_rows = _merge_parquet(GROWTH_PARQUET, wide, key_cols=["farm_id", "crop", "season", "date"])
    log.info("growth_daily.parquet 신규 행: %d", new_rows)
    return new_rows


# ── parquet 증분 병합 헬퍼 ────────────────────────────────────────────────────
def _merge_parquet(path: Path, new_df, key_cols: list[str]) -> int:
    """기존 parquet에 new_df를 증분 추가 (중복 제거). 반환: 실제 신규 행 수."""
    import pandas as pd

    if path.exists():
        try:
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception:
            combined = new_df.copy()
    else:
        combined = new_df.copy()

    before = len(combined)
    combined.drop_duplicates(subset=key_cols, keep="last", inplace=True)
    combined.sort_values(key_cols, inplace=True)
    combined.reset_index(drop=True, inplace=True)
    combined.to_parquet(path, index=False)

    added = len(new_df) - (before - len(combined)) if path.exists() else len(combined)
    return max(0, len(new_df))


# ── 메인 ────────────────────────────────────────────────────────────────────────
def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="야간 DB→Parquet ETL")
    parser.add_argument("--since", default=None,
                        help="이 날짜 이후 데이터 강제 추출 (YYYY-MM-DD). "
                             "기본: parquet 마지막 날짜 자동 감지")
    args, _ = parser.parse_known_args()

    log.info("=== 야간 DB→Parquet ETL 시작 (since=%s) ===", args.since or "auto")
    db_url = _get_db_url()

    try:
        from sqlalchemy import create_engine
        # pg8000 prefix → standard postgresql for SQLAlchemy
        sa_url = db_url.replace("postgresql+pg8000://", "postgresql://") \
                       .replace("postgresql+psycopg2://", "postgresql://")
        # Use psycopg2 driver (installed)
        if "postgresql://" in sa_url and "+psycopg2" not in sa_url and "+pg8000" not in sa_url:
            sa_url = sa_url.replace("postgresql://", "postgresql+psycopg2://")
        engine = create_engine(sa_url, echo=False)
    except Exception as e:
        log.error("DB 연결 실패: %s", e)
        return 1

    new_env = new_prod = 0
    # env: independent connection
    try:
        with engine.connect() as conn:
            new_env = export_env(conn, since=args.since)
    except Exception as e:
        log.exception("env ETL 오류: %s", e)

    # growth: independent connection
    try:
        with engine.connect() as conn:
            new_prod = export_growth(conn)
    except Exception as e:
        log.exception("growth ETL 오류: %s", e)

    _save_state(new_env, new_prod)
    log.info("=== ETL 완료: env+%d prod+%d ===", new_env, new_prod)
    engine.dispose()
    return 0 if (new_env > 0 or new_prod >= 0) else 1


if __name__ == "__main__":
    sys.exit(main())
