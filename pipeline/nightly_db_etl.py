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
def export_env(conn) -> int:
    """
    env_measurements (long) → wide daily pivot.
    컬럼: farm_id, crop, season, year, date, temp_internal_mean, humidity_int_mean, ...
    """
    import pandas as pd

    log.info("env_measurements 읽는 중...")

    # 마지막 parquet 날짜 이후 데이터만 추출 (증분)
    cutoff = "1900-01-01"
    if ENV_PARQUET.exists():
        try:
            existing = pd.read_parquet(ENV_PARQUET, columns=["date"])
            if len(existing):
                cutoff = existing["date"].max()
        except Exception:
            pass

    query = f"""
        SELECT
            em.time::date         AS date,
            em.farm_id,
            em.canonical_name,
            em.value,
            f.crop_type           AS crop,
            EXTRACT(YEAR FROM em.time)::int AS year,
            '1'                   AS season
        FROM env_measurements em
        JOIN farms f ON f.farm_id = em.farm_id
        WHERE em.time::date > '{cutoff}'
          AND (em.quality_tag IS NULL OR em.quality_tag NOT IN ('bad','ERROR'))
        ORDER BY em.farm_id, em.time::date, em.canonical_name
    """
    try:
        df = pd.read_sql(query, conn)
    except Exception as e:
        log.error("env_measurements 쿼리 오류: %s", e)
        return 0

    if df.empty:
        log.info("env: 신규 데이터 없음 (cutoff=%s)", cutoff)
        return 0

    log.info("env 원시 행: %d (farm %d개)", len(df), df["farm_id"].nunique())

    # year/season already in df from SQL query
    # pivot: 각 canonical_name → 통계 컬럼 (mean / max / min / sum)
    AGG_COLS = {
        "temp_internal":    ["mean", "max", "min"],
        "temp_external":    ["mean"],
        "humidity_int":     ["mean"],
        "co2_ppm":          ["mean"],
        "solar_rad":        ["mean", "sum"],
        "ec_dsm":           ["mean"],
        "soil_temp":        ["mean"],
        # 관수 피처
        "wc":               ["mean", "max", "min"],
        "dr_pct":           ["mean"],
        "ec_drain":         ["mean"],
        "supply_total":     ["sum"],
        "irr_count":        ["sum"],
        "nl_pct":           ["mean"],
    }

    pivot_frames = []
    group_keys = ["farm_id", "crop", "season", "year", "date"]

    for canon, stats in AGG_COLS.items():
        sub = df[df["canonical_name"].str.startswith(canon)]
        if sub.empty:
            continue
        for stat in stats:
            col_name = f"{canon}_{stat}"
            agg = sub.groupby(group_keys)["value"].agg(stat).reset_index()
            agg.rename(columns={"value": col_name}, inplace=True)
            pivot_frames.append(agg)

    if not pivot_frames:
        log.warning("pivot 결과 없음 — canonical_name 매핑 확인 필요")
        return 0

    from functools import reduce
    wide = reduce(lambda a, b: a.merge(b, on=group_keys, how="outer"), pivot_frames)
    wide["date"] = pd.to_datetime(wide["date"])

    # 기존 parquet 에 증분 추가
    new_rows = _merge_parquet(ENV_PARQUET, wide, key_cols=["farm_id", "crop", "season", "date"])
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

    GROWTH_COLS = ["plant_height_cm", "leaf_count", "fruit_set_count", "stem_diameter_mm",
                   "yield_kg", "revenue_krw"]
    group_keys = ["farm_id", "crop", "season", "year", "date"]

    pivot_frames = []
    for col in GROWTH_COLS:
        sub = df[df["canonical_name"] == col]
        if sub.empty:
            continue
        stat = "sum" if col in ("yield_kg", "revenue_krw") else "mean"
        agg = sub.groupby(group_keys)["value"].agg(stat).reset_index()
        # clean col names (e.g., plant_height_cm → plant_height)
        clean = col.replace("_cm", "").replace("_mm", "")
        agg.rename(columns={"value": clean}, inplace=True)
        pivot_frames.append(agg)

    if not pivot_frames:
        log.warning("growth pivot 결과 없음")
        return 0

    from functools import reduce
    wide = reduce(lambda a, b: a.merge(b, on=group_keys, how="outer"), pivot_frames)
    wide["date"] = pd.to_datetime(wide["date"])
    wide["year"] = wide["date"].dt.year

    # prod_daily.parquet 도 yield/revenue 포함 (M2 학습 호환)
    prod_cols = [c for c in ["yield_kg", "revenue_krw"] if c in wide.columns]
    if prod_cols:
        prod = wide[group_keys + prod_cols + ["year"]].copy()
        prod["date"] = pd.to_datetime(prod["date"])
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
    log.info("=== 야간 DB→Parquet ETL 시작 ===")
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
            new_env = export_env(conn)
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
