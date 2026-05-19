"""Initial data load pipeline — ingests all 기초자료 CSVs into TimescaleDB (or SQLite).

Load order:
  1. 환경_2025.csv           → iot_sensor_adapter  → env_measurements
  2. 생육_딸기_2025.csv       → rda_api_adapter     → env_measurements (growth GT)
  3. 스마트팜_2018~2022 ZIPs → iot_sensor_adapter  → env_measurements (historical)
  4. 환경생육소득(이암허브)/  → iot_sensor_adapter  → env_measurements (multi-crop)
  5. 핵심학습자료_260506.csv  → registry only (metadata, not time-series)

Run (TimescaleDB):
    python -m pipelines.initial_load --db-url postgresql://user:pass@localhost/smartfarm

Run (SQLite 로컬 테스트):
    python -m pipelines.initial_load --db-url sqlite:///smartfarm.db
    python -m pipelines.initial_load  # DATABASE_URL 환경변수 사용 (없으면 sqlite:///smartfarm.db)

SQLite 모드는 자동으로 테이블을 생성하며 `CREATE TABLE IF NOT EXISTS`를 사용합니다.
TimescaleDB 모드는 스키마가 이미 존재한다고 가정합니다 (migrations/ 참조).
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

# SQLite 기본 URL (TimescaleDB 없이 로컬 테스트용)
_SQLITE_DEFAULT = "sqlite:///smartfarm.db"


def _get_engine(db_url: str):
    """Return SQLAlchemy engine. Import deferred so module loads without sqlalchemy."""
    from sqlalchemy import create_engine
    return create_engine(db_url, future=True)


def _is_sqlite(engine) -> bool:
    return engine.dialect.name == "sqlite"


def _ensure_tables(engine) -> None:
    """SQLite 전용: 필요한 테이블이 없으면 생성."""
    if not _is_sqlite(engine):
        return
    from sqlalchemy import text
    ddl_env = text("""
        CREATE TABLE IF NOT EXISTS env_measurements (
            time        TEXT    NOT NULL,
            farm_id     TEXT    NOT NULL,
            canonical_name TEXT NOT NULL,
            value       REAL,
            source_id   TEXT,
            quality_tag TEXT,
            imputed     INTEGER DEFAULT 0,
            PRIMARY KEY (time, farm_id, canonical_name)
        )
    """)
    ddl_growth = text("""
        CREATE TABLE IF NOT EXISTS growth_measurements (
            time          TEXT NOT NULL,
            farm_id       TEXT NOT NULL,
            crop          TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            value         REAL,
            source_id     TEXT,
            quality_tag   TEXT,
            PRIMARY KEY (time, farm_id, crop, canonical_name)
        )
    """)
    with engine.begin() as conn:
        conn.execute(ddl_env)
        conn.execute(ddl_growth)
    logger.info("SQLite 테이블 확인/생성 완료")


def _insert_records(engine, records) -> int:
    """Bulk-insert NormalizedRecords; returns count inserted.

    SQLite:     INSERT OR IGNORE INTO ...
    PostgreSQL: INSERT INTO ... ON CONFLICT DO NOTHING
    """
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
    if _is_sqlite(engine):
        sql = text(
            """
            INSERT OR IGNORE INTO env_measurements
                (time, farm_id, canonical_name, value, source_id, quality_tag, imputed)
            VALUES (:time, :farm_id, :canonical_name, :value, :source_id, :quality_tag, :imputed)
            """
        )
    else:
        sql = text(
            """
            INSERT INTO env_measurements
                (time, farm_id, canonical_name, value, source_id, quality_tag, imputed)
            VALUES (:time, :farm_id, :canonical_name, :value, :source_id, :quality_tag, :imputed)
            ON CONFLICT (time, farm_id, canonical_name) DO NOTHING
            """
        )
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


def _insert_growth_records(engine, rows: list[dict]) -> int:
    """Bulk-insert growth records into growth_measurements table.

    SQLite:     INSERT OR IGNORE INTO ...
    PostgreSQL: INSERT INTO ... ON CONFLICT DO NOTHING
    """
    if not rows:
        return 0
    from sqlalchemy import text
    if _is_sqlite(engine):
        sql = text(
            """
            INSERT OR IGNORE INTO growth_measurements
                (time, farm_id, crop, canonical_name, value, source_id, quality_tag)
            VALUES
                (:time, :farm_id, :crop, :canonical_name, :value, :source_id, :quality_tag)
            """
        )
    else:
        sql = text(
            """
            INSERT INTO growth_measurements
                (time, farm_id, crop, canonical_name, value, source_id, quality_tag)
            VALUES
                (:time, :farm_id, :crop, :canonical_name, :value, :source_id, :quality_tag)
            ON CONFLICT (time, farm_id, crop, canonical_name) DO NOTHING
            """
        )
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


# 생육 컬럼 → canonical 이름 매핑
_GROWTH_CANON: dict[str, str] = {
    "초장":           "plant_height",
    "엽수":           "leaf_count",
    "엽장":           "leaf_length",
    "엽폭":           "leaf_width",
    "관부직경":       "crown_diameter",
    "착과수":         "fruit_count",
    "화방별착과수":   "fruit_count",
    "마디수":         "node_count",
    "줄기굵기":       "stem_diameter",
    "생장길이":       "plant_height",   # 방울토마토/완숙토마토 별칭
}

# 파일명 작목 키워드 → 한글 작목명
_FILENAME_CROP: list[tuple[str, str]] = [
    ("방울토마토", "방울토마토"),
    ("완숙토마토", "완숙토마토"),
    ("딸기",      "딸기"),
    ("참외",      "참외"),
    ("오이",      "오이"),
    ("파프리카",  "파프리카"),
]


def _parse_growth_csv(df, crop: str, farm_id: str, source_id: str = "rda_api") -> list[dict]:
    """생육 CSV DataFrame → growth_measurements 삽입용 행 목록."""
    import pandas as pd
    import numpy as np

    # 날짜 컬럼 탐색
    date_col = next(
        (c for c in df.columns if "조사일" in c or "측정일" in c or "일시" in c), None
    )
    if date_col is None:
        return []

    df = df.copy()
    df["_time"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["_time"])

    rows: list[dict] = []
    for orig, canon in _GROWTH_CANON.items():
        if orig not in df.columns:
            continue
        col = pd.to_numeric(df[orig], errors="coerce")
        valid = col.dropna()
        for idx in valid.index:
            v = float(valid[idx])
            if v <= 0 or v > 9999:   # 유효 범위 최소 필터
                continue
            rows.append({
                "time":           df.at[idx, "_time"].to_pydatetime(),
                "farm_id":        farm_id,
                "crop":           crop,
                "canonical_name": canon,
                "value":          v,
                "source_id":      source_id,
                "quality_tag":    "FINETUNED",
            })
    return rows


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


def load_growth_panel(engine) -> int:
    """Load 생육_[작목]_2018~2022.csv from ZIP archives → growth_measurements.

    순서:
      1. 스마트팜_YYYY.zip 내 생육_[작목]_YYYY.csv 탐색
      2. _parse_growth_csv() 로 정제
      3. growth_measurements 테이블에 삽입

    ZIP 파일명이 EUC-KR 인코딩된 경우 latin-1 → euc-kr 변환 적용.
    """
    import io
    import pandas as pd

    total = 0
    zip_pattern = str(DATA_DIR / "**" / "스마트팜_*.zip")
    zip_files = glob.glob(zip_pattern, recursive=True)
    if not zip_files:
        logger.info("[load_growth_panel] 농진청 5년 ZIP 없음 — 스킵")
        return 0

    # farm_id 결정: 농진청 5년 패널은 다중 농가 → 파일 내 농가ID 컬럼 사용,
    # 없으면 기본값 "rda_panel" 사용
    for zip_path in sorted(zip_files):
        logger.info("[load_growth_panel] ZIP 처리: %s", zip_path)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    # 파일명 EUC-KR 디코딩
                    try:
                        name = info.filename.encode("latin-1").decode("euc-kr")
                    except Exception:
                        name = info.filename

                    # 생육_[작목]_YYYY.csv 패턴만 처리
                    basename = name.split("/")[-1]
                    if not (basename.startswith("생육_") and basename.endswith(".csv")):
                        continue

                    # 작목명 추출
                    crop = None
                    for keyword, crop_ko in _FILENAME_CROP:
                        if keyword in basename:
                            crop = crop_ko
                            break
                    if crop is None:
                        logger.debug("[load_growth_panel] 작목 미인식: %s", basename)
                        continue

                    try:
                        raw = zf.read(info.filename)
                        df = pd.read_csv(
                            io.BytesIO(raw), encoding="euc-kr", low_memory=False
                        )
                    except Exception as exc:
                        logger.warning("[load_growth_panel] %s 읽기 실패: %s", basename, exc)
                        continue

                    # 농가 ID 컬럼 탐색 (있으면 사용, 없으면 "rda_panel")
                    farm_col = next(
                        (c for c in df.columns if "농가" in c and "번호" in c), None
                    ) or next((c for c in df.columns if "농가" in c), None)

                    if farm_col:
                        # 농가별로 묶어서 삽입
                        for farm_raw, gdf in df.groupby(df[farm_col].astype(str).str.strip()):
                            farm_id = f"rda_{farm_raw}"
                            rows = _parse_growth_csv(gdf, crop, farm_id)
                            n = _insert_growth_records(engine, rows)
                            total += n
                    else:
                        rows = _parse_growth_csv(df, crop, "rda_panel")
                        n = _insert_growth_records(engine, rows)
                        total += n

                    logger.info(
                        "[load_growth_panel]  %s → crop=%s: %d 행 삽입", basename, crop, n
                    )
        except zipfile.BadZipFile as exc:
            logger.warning("[load_growth_panel] 불량 ZIP %s: %s", zip_path, exc)

    logger.info("[load_growth_panel] 전체 삽입: %d행", total)
    return total


def load_growth_eeamhub(engine) -> int:
    """이암허브 생육데이터_[작목].zip → growth_measurements 적재."""
    import io
    import pandas as pd

    crop_dir = (
        DATA_DIR
        / "농진청빅데이터-20260509T093516Z-3-001"
        / "농진청빅데이터"
        / "환경생육소득(이암허브)"
    )
    if not crop_dir.exists():
        logger.info("[load_growth_eeamhub] 이암허브 디렉터리 없음 — 스킵")
        return 0

    total = 0
    for zip_path in sorted(crop_dir.glob("생육데이터_*.zip")):
        # 파일명에서 작목명 추출: 생육데이터_딸기.zip → 딸기
        stem = zip_path.stem  # "생육데이터_딸기"
        crop = None
        for keyword, crop_ko in _FILENAME_CROP:
            if keyword in stem:
                crop = crop_ko
                break
        if crop is None:
            logger.debug("[load_growth_eeamhub] 작목 미인식: %s", zip_path.name)
            continue

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if not info.filename.lower().endswith(".csv"):
                        continue
                    try:
                        raw = zf.read(info.filename)
                        df = pd.read_csv(io.BytesIO(raw), encoding="euc-kr", low_memory=False)
                    except Exception as exc:
                        logger.warning("[load_growth_eeamhub] %s 읽기 실패: %s", info.filename, exc)
                        continue
                    rows = _parse_growth_csv(df, crop, "farm_001", source_id="eeamhub")
                    n = _insert_growth_records(engine, rows)
                    total += n
                    logger.info(
                        "[load_growth_eeamhub]  %s → crop=%s: %d행", info.filename, crop, n
                    )
        except zipfile.BadZipFile as exc:
            logger.warning("[load_growth_eeamhub] 불량 ZIP %s: %s", zip_path.name, exc)

    logger.info("[load_growth_eeamhub] 전체 삽입: %d행", total)
    return total


def run(db_url: str) -> None:
    engine = _get_engine(db_url)
    dialect = engine.dialect.name
    logger.info("DB 방언: %s  (URL: %s)", dialect, db_url.split("@")[-1])
    # SQLite는 테이블 자동 생성, PostgreSQL/TimescaleDB는 migrations/ DDL 사용
    _ensure_tables(engine)
    total = 0
    total += load_env_2025(engine)
    total += load_growth_2025(engine)
    total += load_historical_zips(engine)
    total += load_multi_crop_data(engine)
    total += load_growth_panel(engine)        # 농진청 5년 생육 → growth_measurements
    total += load_growth_eeamhub(engine)      # 이암허브 생육   → growth_measurements
    logger.info("=== Initial load complete: %d records total ===", total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Farm initial data load")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", _SQLITE_DEFAULT),
        help=(
            "SQLAlchemy DB URL. "
            "PostgreSQL 예: postgresql://user:pass@localhost/smartfarm  "
            "SQLite 예: sqlite:///smartfarm.db  "
            f"기본값: {_SQLITE_DEFAULT} (환경변수 DATABASE_URL 없을 때)"
        ),
    )
    args = parser.parse_args()
    run(args.db_url)
