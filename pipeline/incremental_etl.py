"""증분 ETL 파이프라인

신규 센서 CSV → 정규화 → 일별 집계 → env_daily.parquet / prod_daily.parquet에 증분 추가.

사용:
    python incremental_etl.py --env_csv <path> [--prod_csv <path>] [--crop 딸기] [--farm_id FARM_X]

규칙:
  - (farm_id, crop, date) 기준 중복 행 제거 (기존 데이터 우선)
  - 신규 행 수를 pipeline/state/new_rows_since_retrain.json 에 누적
  - 처리 로그: pipeline/logs/incremental_etl.log
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── 경로 설정 ──────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
ETL_DIR   = ROOT.parent / "outputs" / "etl"          # 학습용 parquet 저장소
STATE_DIR = ROOT / "pipeline" / "state"
LOG_DIR   = ROOT / "pipeline" / "logs"
for d in [ETL_DIR, STATE_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

ENV_PARQUET  = ETL_DIR / "env_daily.parquet"
PROD_PARQUET = ETL_DIR / "prod_daily.parquet"
STATE_FILE   = STATE_DIR / "new_rows_since_retrain.json"

# ── 컬럼 정규화 맵 ─────────────────────────────────────────────────────────
_COL_MAP = {
    "온도": "temp_internal_mean", "내부온도": "temp_internal_mean",
    "습도": "humidity_int_mean",  "내부습도": "humidity_int_mean",
    "co2": "co2_ppm_mean",        "co2농도": "co2_ppm_mean",
    "일사": "solar_rad_mean",     "일사량": "solar_rad_mean",
    "ec":  "ec_dsm_mean",
    "수확량": "yield_kg",         "생산량": "yield_kg",
    "매출": "revenue_krw",
    # 관수 데이터 컬럼 매핑
    "함수율평균": "wc_mean",      "wc평균": "wc_mean",
    "함수율최대": "wc_max",       "함수율최소": "wc_min",
    "배액률": "dr_pct_mean",      "배액률평균": "dr_pct_mean",
    "배액ec": "ec_drain",         "배액ec평균": "ec_drain",
    "총공급량": "supply_total",   "공급량합계": "supply_total",
    "관수횟수": "irr_count",      "야간소실률": "nl_pct",
}

ENV_COLS  = ["temp_internal_mean", "temp_internal_max", "temp_internal_min",
             "humidity_int_mean", "co2_ppm_mean", "solar_rad_mean", "solar_rad_sum",
             "ec_dsm_mean"]

# P4 관수 관리 피처 (관수통합관리시스템 연동)
IRR_COLS  = ["wc_mean", "wc_max", "wc_min",
             "dr_pct_mean", "ec_drain",
             "supply_total", "irr_count", "nl_pct"]
PROD_COLS = ["yield_kg", "revenue_krw"]
KEY_COLS  = ["farm_id", "crop", "date"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "incremental_etl.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("incremental_etl")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "") for c in df.columns]
    df = df.rename(columns={k: v for k, v in _COL_MAP.items() if k in df.columns})
    return df


def _read_csv_auto(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "euc-kr", "utf-8"]:
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False)
        except Exception:
            continue
    raise ValueError(f"Cannot read CSV: {path}")


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"new_env_rows": 0, "new_prod_rows": 0, "last_updated": None}


def _save_state(state: dict) -> None:
    state["last_updated"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_dedup(existing_path: Path, new_df: pd.DataFrame, key_cols: list[str]) -> int:
    """기존 parquet에 new_df를 증분 추가하고 key_cols 기준 중복 제거.

    Returns:
        실제 추가된 신규 행 수
    """
    new_df = new_df.copy()
    new_df["date"] = pd.to_datetime(new_df["date"])

    if existing_path.exists():
        existing = pd.read_parquet(existing_path)
        existing["date"] = pd.to_datetime(existing["date"])

        # 기존에 없는 키만 추출
        existing_keys = set(zip(*[existing[c].astype(str) for c in key_cols]))
        mask = ~new_df.apply(
            lambda r: tuple(str(r[c]) for c in key_cols) in existing_keys, axis=1
        )
        truly_new = new_df[mask]

        if len(truly_new) == 0:
            logger.info("  중복 없음: 추가된 행 0개")
            return 0

        combined = pd.concat([existing, truly_new], ignore_index=True)
    else:
        truly_new = new_df
        combined = new_df

    combined.to_parquet(existing_path, index=False)
    logger.info("  %d개 신규 행 추가 (전체 %d행)", len(truly_new), len(combined))
    return len(truly_new)


def process_env_csv(
    csv_path: Path,
    farm_id: str,
    crop: str,
    season: str = "1",
) -> int:
    """환경 센서 CSV를 읽어 일별 집계 후 env_daily.parquet에 증분 추가."""
    logger.info("[ENV] 처리 시작: %s (farm=%s, crop=%s)", csv_path.name, farm_id, crop)
    df = _read_csv_auto(csv_path)
    df = _normalize_columns(df)

    # 날짜 파싱
    date_candidates = ["date", "datetime", "timestamp", "일자", "날짜"]
    date_col = next((c for c in date_candidates if c in df.columns), None)
    if date_col is None:
        raise ValueError(f"날짜 컬럼을 찾을 수 없음. 컬럼 목록: {list(df.columns)}")
    df["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"])

    # 숫자 컬럼 변환
    for col in ENV_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 일별 집계
    agg = {"temp_internal_mean": "mean", "temp_internal_max": "max",
           "temp_internal_min": "min", "humidity_int_mean": "mean",
           "co2_ppm_mean": "mean", "solar_rad_mean": "mean",
           "solar_rad_sum": "sum", "ec_dsm_mean": "mean"}
    available = {k: v for k, v in agg.items() if k in df.columns}
    daily = df.groupby("date").agg(available).reset_index()
    daily["farm_id"] = farm_id
    daily["crop"]    = crop
    daily["season"]  = season
    daily["year"]    = daily["date"].dt.year

    added = _append_dedup(ENV_PARQUET, daily, KEY_COLS)
    return added


def process_prod_csv(
    csv_path: Path,
    farm_id: str,
    crop: str,
    season: str = "1",
) -> int:
    """생산량 CSV를 읽어 prod_daily.parquet에 증분 추가."""
    logger.info("[PROD] 처리 시작: %s (farm=%s, crop=%s)", csv_path.name, farm_id, crop)
    df = _read_csv_auto(csv_path)
    df = _normalize_columns(df)

    date_col = next((c for c in ["date","datetime","일자","날짜"] if c in df.columns), None)
    if date_col is None:
        raise ValueError("날짜 컬럼 없음")
    df["date"]    = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df["farm_id"] = farm_id
    df["crop"]    = crop
    df["season"]  = season
    df["year"]    = df["date"].dt.year

    for col in PROD_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    added = _append_dedup(PROD_PARQUET, df, KEY_COLS)
    return added


def run(args: argparse.Namespace) -> None:
    state = _load_state()
    total_new = 0

    if args.env_csv:
        n = process_env_csv(Path(args.env_csv), args.farm_id, args.crop, args.season)
        state["new_env_rows"] += n
        total_new += n

    if args.prod_csv:
        n = process_prod_csv(Path(args.prod_csv), args.farm_id, args.crop, args.season)
        state["new_prod_rows"] += n
        total_new += n

    _save_state(state)
    logger.info("[완료] 신규 행 %d개 추가 (누적: env=%d, prod=%d)",
                total_new, state["new_env_rows"], state["new_prod_rows"])


def main() -> None:
    parser = argparse.ArgumentParser(description="스마트팜 증분 ETL")
    parser.add_argument("--env_csv",  help="환경 센서 CSV 경로")
    parser.add_argument("--prod_csv", help="생산량 CSV 경로")
    parser.add_argument("--farm_id",  required=True, help="농가 ID")
    parser.add_argument("--crop",     required=True, help="작물명 (한국어)")
    parser.add_argument("--season",   default="1", help="시즌 번호")
    args = parser.parse_args()

    if not args.env_csv and not args.prod_csv:
        parser.error("--env_csv 또는 --prod_csv 중 하나 이상 필요")

    run(args)


if __name__ == "__main__":
    main()
