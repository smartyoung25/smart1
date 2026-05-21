"""ETL directory scanner — called by cron inside the pipeline container.

Scans a directory for unprocessed CSV files and runs incremental_etl.py
on each one, then moves processed files to a done/ subdirectory.

Usage:
    python pipeline/run_etl_dir.py /app/etl_data [--dry-run]

Expected filename convention:
    {farm_id}__{crop}__{season}__{type}.csv
    e.g.  farm001__strawberry__1__env.csv
          farm001__딸기__1__env.csv
          farm001__딸기__1__prod.csv

Any CSV not matching the convention is logged and skipped.
"""
from __future__ import annotations
import argparse, logging, shutil, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

CROP_NORM: dict[str, str] = {
    "strawberry": "딸기", "cherry_tomato": "방울토마토",
    "tomato": "완숙토마토", "melon": "참외", "paprika": "파프리카",
    "딸기": "딸기", "방울토마토": "방울토마토",
    "완숙토마토": "완숙토마토", "참외": "참외", "파프리카": "파프리카",
}


def _parse_filename(path: Path) -> dict | None:
    """Parse farm_id, crop, season, type from filename convention."""
    stem = path.stem  # strip .csv
    parts = stem.split("__")
    if len(parts) < 4:
        return None
    farm_id, crop_raw, season, ftype = parts[0], parts[1], parts[2], parts[3]
    crop_ko = CROP_NORM.get(crop_raw)
    if crop_ko is None:
        log.warning("알 수 없는 작물명: %s (%s)", crop_raw, path.name)
        return None
    if ftype not in ("env", "prod"):
        log.warning("알 수 없는 파일 유형: %s (%s)", ftype, path.name)
        return None
    return {"farm_id": farm_id, "crop": crop_ko, "season": season, "type": ftype}


def run(data_dir: Path, dry_run: bool = False) -> int:
    """Scan data_dir for unprocessed CSV files, run ETL on each pair."""
    if not data_dir.exists():
        log.error("디렉토리 없음: %s", data_dir)
        return 1

    done_dir = data_dir / "done"
    done_dir.mkdir(exist_ok=True)

    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        log.info("처리할 CSV 파일 없음: %s", data_dir)
        return 0

    log.info("%d개 CSV 발견", len(csv_files))

    # Group by (farm_id, crop, season) so env+prod can be passed together
    from collections import defaultdict
    groups: dict[tuple, dict] = defaultdict(dict)
    skip = 0
    for f in csv_files:
        meta = _parse_filename(f)
        if meta is None:
            log.warning("스킵 (파일명 규칙 불일치): %s", f.name)
            skip += 1
            continue
        key = (meta["farm_id"], meta["crop"], meta["season"])
        groups[key][meta["type"]] = f

    log.info("%d개 농가-작물-시즌 그룹 / %d개 스킵", len(groups), skip)

    processed = errors = 0
    for (farm_id, crop, season), files in groups.items():
        env_csv  = files.get("env")
        prod_csv = files.get("prod")

        cmd_parts = [
            sys.executable, "-B",
            str(ROOT / "pipeline" / "incremental_etl.py"),
            "--farm_id", farm_id,
            "--crop",    crop,
            "--season",  season,
        ]
        if env_csv:  cmd_parts += ["--env_csv",  str(env_csv)]
        if prod_csv: cmd_parts += ["--prod_csv", str(prod_csv)]

        log.info("ETL 실행: farm=%s crop=%s season=%s env=%s prod=%s",
                 farm_id, crop, season,
                 env_csv.name if env_csv else "-",
                 prod_csv.name if prod_csv else "-")

        if dry_run:
            log.info("  [dry-run] %s", " ".join(cmd_parts))
            processed += 1
            continue

        import subprocess
        result = subprocess.run(cmd_parts, capture_output=True, text=True)
        if result.returncode == 0:
            log.info("  완료")
            # Move processed files to done/
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            for f in files.values():
                dest = done_dir / f"{f.stem}__{ts}{f.suffix}"
                shutil.move(str(f), str(dest))
            processed += 1
        else:
            err_tail = result.stderr[:300]
            log.error("  실패 (rc=%d): %s", result.returncode, err_tail)
            errors += 1
            # 오류 알림
            try:
                from pipeline.notifier import notify_etl_error
                src_file = env_csv or prod_csv
                notify_etl_error(
                    farm_id=farm_id,
                    error_msg=f"rc={result.returncode}\n{err_tail}",
                    filename=src_file.name if src_file else None,
                )
            except Exception as ne:
                log.warning("알림 발송 오류 (무시): %s", ne)

    log.info("완료: 처리=%d 에러=%d 스킵=%d", processed, errors, skip)
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL 디렉토리 스캐너")
    parser.add_argument("data_dir", help="스캔할 CSV 디렉토리 경로")
    parser.add_argument("--dry-run", action="store_true", help="실제 실행 없이 로그만 출력")
    args = parser.parse_args()
    sys.exit(run(Path(args.data_dir), dry_run=args.dry_run))
