"""Initial data load pipeline — ingests all 기초자료 CSVs into TimescaleDB.

Load order:
  1. 환경_2025.csv           → iot_sensor_adapter  → env_measurements
  2. 생육_딸기_2025.csv       → rda_api_adapter     → env_measurements (growth GT)
  3. 스마트팜_2018~2022 ZIPs → iot_sensor_adapter  → env_measurements (historical)
  4. 환경생육소득(이암허브)/  → iot_sensor_adapter  → env_measurements (multi-crop)
  5. 핵심학습자료_260506.csv  → registry only (metadata, not time-series)

Run:
    python -m pipelines.initial_load --db-url postgresql://user:pass@localhost/smartfarm
"""
from __future__ import annotations
import argparse
import glob
import logging
import os
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "기초자료"

# Farm ID for 이암허브 farm
EEAM_FARM_ID = "farm_001"


def _get_engine(db_url: str):
    """Return SQLAlchemy engine. Import deferred so module loads without sqlalchemy."""
    from sqlalchemy import create_engine
    return create_engine(db_url)


def _insert_records(engine, records) -> int:
    """Bulk-insert NormalizedRecords; returns count inserted."""
    if not records:
        return 0
    from sqlalchemy import text
    rows = [
        {
            "time": r.time,
            "farm_id": r.farm_id,
            "canonical_name": r.canonical_name,
            "value": r.value,
            "source_id": r.source_id,
            "quality_tag": r.quality_tag,
            "imputed": r.imputed,
        }
        for r in records
    ]
    sql = text(
        """
        INSERT INTO env_measurements (time, farm_id, canonical_name, value, source_id, quality_tag, imputed)
        VALUES (:time, :farm_id, :canonical_name, :value, :source_id, :quality_tag, :imputed)
        ON CONFLICT (time, farm_id, canonical_name) DO NOTHING
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def load_env_2025(engine, farm_id: str = EEAM_FARM_ID) -> int:
    """Load 환경_2025.csv from 이암허브 directory."""
    import pandas as pd
    from adapters.iot_sensor_adapter import adapt_dataframe

    csv_path = (
        DATA_DIR
        / "농진청빅데이터-20260509T093516Z-3-001"
        / "농진청빅데이터"
        / "스마트팜(이암허브)"
        / "환경_2025.csv"
    )
    if not csv_path.exists():
        logger.warning("환경_2025.csv not found at %s", csv_path)
        return 0

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    result = adapt_dataframe(df, farm_id=farm_id)
    for err in result.errors:
        logger.warning(err)
    count = _insert_records(engine, result.records)
    logger.info("환경_2025.csv: inserted %d records", count)
    return count


def load_growth_2025(engine, farm_id: str = EEAM_FARM_ID) -> int:
    """Load 생육_딸기_2025.csv — growth Ground Truth for M1."""
    import pandas as pd
    from adapters.rda_api_adapter import adapt_response_list

    csv_path = (
        DATA_DIR
        / "농진청빅데이터-20260509T093516Z-3-001"
        / "농진청빅데이터"
        / "스마트팜(이암허브)"
        / "생육_딸기_2025.csv"
    )
    if not csv_path.exists():
        logger.warning("생육_딸기_2025.csv not found at %s", csv_path)
        return 0

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    items = df.to_dict(orient="records")
    result = adapt_response_list(items, farm_id=farm_id, time_key="측정일시")
    for err in result.errors:
        logger.warning(err)
    count = _insert_records(engine, result.records)
    logger.info("생육_딸기_2025.csv: inserted %d records", count)
    return count


def load_historical_zips(engine, farm_id: str = EEAM_FARM_ID) -> int:
    """Load 스마트팜_2018~2022 ZIP archives (historical baseline)."""
    import pandas as pd
    from adapters.iot_sensor_adapter import adapt_dataframe

    total = 0
    zip_pattern = str(DATA_DIR / "**" / "스마트팜_*.zip")
    zip_files = glob.glob(zip_pattern, recursive=True)
    if not zip_files:
        logger.info("No historical ZIP files found under %s", DATA_DIR)
        return 0

    for zip_path in zip_files:
        logger.info("Processing ZIP: %s", zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if not name.lower().endswith(".csv"):
                    continue
                with zf.open(name) as f:
                    try:
                        df = pd.read_csv(f, encoding="utf-8-sig")
                    except Exception as exc:
                        logger.warning("Could not read %s in %s: %s", name, zip_path, exc)
                        continue
                result = adapt_dataframe(df, farm_id=farm_id)
                for err in result.errors:
                    logger.debug(err)
                count = _insert_records(engine, result.records)
                total += count
                logger.info("  %s: inserted %d records", name, count)
    logger.info("Historical ZIPs total: %d records", total)
    return total


def load_multi_crop_data(engine) -> int:
    """Load 환경생육소득(이암허브)/ directory — multi-crop historical data."""
    import pandas as pd
    from adapters.iot_sensor_adapter import adapt_dataframe

    crop_dir = DATA_DIR / "환경생육소득(이암허브)"
    if not crop_dir.exists():
        # try alternative naming
        crop_dir = DATA_DIR / "농진청빅데이터-20260509T093516Z-3-001" / "농진청빅데이터" / "환경생육소득(이암허브)"
    if not crop_dir.exists():
        logger.info("환경생육소득 directory not found, skipping")
        return 0

    total = 0
    # Farm ID mapping by crop subfolder name
    crop_farm_map = {
        "딸기": "farm_001",
        "토마토": "farm_003",
        "방울토마토": "farm_002",
        "멜론": "farm_004",
    }
    for csv_path in crop_dir.rglob("*.csv"):
        farm_id = "farm_001"
        for crop_keyword, fid in crop_farm_map.items():
            if crop_keyword in str(csv_path):
                farm_id = fid
                break
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        except Exception as exc:
            logger.warning("Could not read %s: %s", csv_path, exc)
            continue
        result = adapt_dataframe(df, farm_id=farm_id)
        count = _insert_records(engine, result.records)
        total += count
        logger.info("%s → farm %s: inserted %d records", csv_path.name, farm_id, count)
    logger.info("Multi-crop data total: %d records", total)
    return total


def run(db_url: str) -> None:
    engine = _get_engine(db_url)
    total = 0
    total += load_env_2025(engine)
    total += load_growth_2025(engine)
    total += load_historical_zips(engine)
    total += load_multi_crop_data(engine)
    logger.info("=== Initial load complete: %d records total ===", total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Farm initial data load")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost/smartfarm"),
        help="SQLAlchemy database URL",
    )
    args = parser.parse_args()
    run(args.db_url)
