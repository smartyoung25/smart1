"""훈련 데이터 설정 스크립트.

실제 농진청 ZIP 데이터가 없을 때 합성 데이터를 생성하거나,
DATA_DIR 경로를 .env / crop_config.py 에서 재설정하는 방법을 안내한다.

사용법:
  # 합성 데이터 생성 (기본: 모든 작목, 2018~2022, 각 5농가)
  python scripts/setup_training_data.py --mode synthetic

  # 실제 데이터 경로 확인
  python scripts/setup_training_data.py --mode check

  # 데이터 경로를 직접 지정 (crop_config.py 패치)
  python scripts/setup_training_data.py --mode patch --data-path "D:/rda_data"
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ── 합성 데이터 파라미터 ──────────────────────────────────────────────────────

CROPS_CONFIG = {
    "딸기": {
        "crop_en": "strawberry",
        "env": {"온도_내부": (16, 22), "상대습도_내부": (55, 80), "잔존CO2": (600, 1200),
                "토양온도": (14, 20), "일사량_외부": (50, 400), "온도_외부": (5, 20), "풍속_외부": (0, 5)},
        "growth": {"초장": (10, 40), "엽수": (4, 15), "엽장": (5, 15), "엽폭": (4, 12), "화방별착과수": (3, 18)},
        "yield_kg_m2": (2.5, 4.5),   # kg/m²/작기
        "season": [10, 11, 12, 1, 2, 3, 4, 5],
        "n_farms": 6,
    },
    "방울토마토": {
        "crop_en": "cherry_tomato",
        "env": {"온도_내부": (18, 28), "상대습도_내부": (55, 80), "잔존CO2": (600, 1400),
                "토양온도": (18, 25), "일사량_외부": (80, 600), "온도_외부": (8, 30), "풍속_외부": (0, 6)},
        "growth": {"초장": (20, 200), "생장길이": (2, 12), "엽수": (8, 25), "엽장": (8, 18),
                   "엽폭": (6, 16), "줄기굵기": (5, 18), "화방별꽃수": (3, 15), "화방별개화수": (2, 12), "화방별착과수": (2, 10)},
        "yield_kg_m2": (12.0, 20.0),
        "season": list(range(1, 13)),
        "n_farms": 5,
    },
    "완숙토마토": {
        "crop_en": "tomato",
        "env": {"온도_내부": (18, 28), "상대습도_내부": (55, 80), "잔존CO2": (600, 1400),
                "토양온도": (18, 25), "일사량_외부": (80, 600), "온도_외부": (8, 30), "풍속_외부": (0, 6)},
        "growth": {"초장": (30, 250), "생장길이": (2, 14), "엽수": (10, 30), "엽장": (10, 22),
                   "엽폭": (8, 20), "줄기굵기": (6, 20), "화방별꽃수": (3, 12), "화방별개화수": (2, 10),
                   "화방별착과수": (2, 8), "개화군": (1, 6), "착과군": (1, 6)},
        "yield_kg_m2": (15.0, 25.0),
        "season": list(range(1, 13)),
        "n_farms": 5,
    },
    "참외": {
        "crop_en": "melon",
        "env": {"온도_내부": (22, 32), "상대습도_내부": (55, 75), "잔존CO2": (400, 1200),
                "토양온도": (18, 28), "일사량_외부": (100, 700), "온도_외부": (15, 35), "풍속_외부": (0, 7)},
        "growth": {"초장": (30, 200), "마디수": (8, 30), "평균절간장": (3, 10), "줄기굵기": (5, 15),
                   "엽장": (8, 20), "엽폭": (7, 18), "엽수": (8, 25), "암꽃수": (1, 8), "착과수": (1, 6)},
        "yield_kg_m2": (14.0, 22.0),
        "season": [3, 4, 5, 6, 7, 8],
        "n_farms": 4,
    },
    "파프리카": {
        "crop_en": "paprika",
        "env": {"온도_내부": (20, 28), "상대습도_내부": (60, 80), "잔존CO2": (600, 1400),
                "토양온도": (18, 25), "일사량_외부": (80, 600), "온도_외부": (8, 30), "풍속_외부": (0, 6)},
        "growth": {"초장": (30, 180), "생장길이": (2, 12), "엽수": (8, 20), "엽장": (8, 16),
                   "엽폭": (6, 14), "줄기굵기": (6, 18), "화방높이": (10, 60), "개화마디": (3, 15), "착과마디": (3, 15)},
        "yield_kg_m2": (18.0, 28.0),
        "season": list(range(1, 13)),
        "n_farms": 4,
    },
    "오이": {
        "crop_en": "cucumber",
        "env": {"온도_내부": (20, 30), "상대습도_내부": (60, 85), "잔존CO2": (500, 1300),
                "토양온도": (18, 26), "일사량_외부": (80, 550), "온도_외부": (10, 32), "풍속_외부": (0, 6)},
        "growth": {"초장": (20, 250), "마디수": (10, 40), "줄기굵기": (5, 18), "엽수": (8, 25),
                   "엽장": (10, 22), "엽폭": (8, 20), "착과수": (1, 8)},
        "yield_kg_m2": (15.0, 22.0),
        "season": [3, 4, 5, 6, 7, 8, 9, 10],
        "n_farms": 4,
    },
}

YEARS_SYNTHETIC = [2018, 2019, 2020, 2021, 2022]
RNG = np.random.default_rng(42)


# ── 환경 데이터 생성 ──────────────────────────────────────────────────────────

def _make_env_df(crop_ko: str, cfg: dict, year: int, n_per_month: int = 720) -> pd.DataFrame:
    """작목별 환경 시계열 DataFrame 생성 (월 720행 = 30일×24h)."""
    rows = []
    env_ranges = cfg["env"]
    season_months = cfg.get("season", list(range(1, 13)))
    n_farms = cfg.get("n_farms", 4)
    farm_ids = [str(i + 1) for i in range(n_farms)]

    for month in range(1, 13):
        if month not in season_months:
            continue
        for farm_id in farm_ids:
            # 농가별 환경 기준값에 약간의 편차 부여
            farm_offset = (int(farm_id) - 1) * 0.5
            # 30일 × 24시간 시계열
            for day in range(1, 31):
                for hour in range(24):
                    try:
                        dt_str = f"{year:04d}-{month:02d}-{min(day,28):02d} {hour:02d}:00:00"
                        row = {
                            "측정시간": dt_str,
                            "농가명": farm_id,
                            "품목": crop_ko,
                            "year": year,
                            "month": month,
                        }
                        for col, (lo, hi) in env_ranges.items():
                            base = (lo + hi) / 2 + farm_offset
                            noise = RNG.normal(0, (hi - lo) * 0.05)
                            # 일내 변화 패턴 (온도 등)
                            if "온도" in col:
                                diurnal = 2.0 * np.sin(2 * np.pi * (hour - 6) / 24)
                                row[col] = round(np.clip(base + noise + diurnal, lo, hi), 2)
                            else:
                                row[col] = round(np.clip(base + noise, lo, hi), 2)
                        rows.append(row)
                    except Exception:
                        pass

    return pd.DataFrame(rows)


# ── 생육 데이터 생성 ──────────────────────────────────────────────────────────

def _make_growth_df(crop_ko: str, cfg: dict, year: int, n_per_month: int = 4) -> pd.DataFrame:
    """작목별 생육 관측 DataFrame 생성 (월 4회 조사)."""
    rows = []
    growth_ranges = cfg["growth"]
    yield_lo, yield_hi = cfg["yield_kg_m2"]
    season_months = cfg.get("season", list(range(1, 13)))
    n_farms = cfg.get("n_farms", 4)
    farm_ids = [str(i + 1) for i in range(n_farms)]

    for month in range(1, 13):
        if month not in season_months:
            continue
        for farm_id in farm_ids:
            farm_seed = int(farm_id) * 100 + month
            is_harvest_month = (month == season_months[-1]) if season_months else False

            for obs in range(n_per_month):
                try:
                    day = (obs + 1) * 7  # 7일 간격
                    dt_str = f"{year:04d}-{month:02d}-{min(day,28):02d}"
                    row = {
                        "조사일자": dt_str,
                        "농가명": farm_id,
                        "품목": crop_ko,
                        "year": year,
                        "month": month,
                    }
                    # 생육 변수
                    growth_factor = 0.5 + 0.5 * (obs / n_per_month)  # 월 내 성장 반영
                    for col, (lo, hi) in growth_ranges.items():
                        base   = lo + (hi - lo) * growth_factor
                        noise  = RNG.normal(0, (hi - lo) * 0.1)
                        row[col] = round(max(lo * 0.5, base + noise), 2)

                    # 수확량 (마지막 관측 시점에만 기록)
                    if obs == n_per_month - 1:
                        area_m2 = RNG.uniform(800, 2500)
                        yield_m2 = RNG.uniform(yield_lo, yield_hi)
                        row["재배면적"] = round(area_m2, 1)
                        row["수확량"] = round(yield_m2 * area_m2, 1)
                        row["yield_per_m2"] = round(yield_m2, 4)

                    rows.append(row)
                except Exception:
                    pass

    return pd.DataFrame(rows)


# ── ZIP 생성 ──────────────────────────────────────────────────────────────────

def create_zip(year: int, data_dir: Path) -> Path:
    """단일 연도 ZIP 파일 생성 (환경 + 생육 CSVs for all crops)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / f"스마트팜_{year}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for crop_ko, cfg in CROPS_CONFIG.items():
            logger.info("  [%d] %s 환경 데이터 생성 중...", year, crop_ko)
            env_df = _make_env_df(crop_ko, cfg, year)
            if len(env_df) == 0:
                continue
            buf = io.BytesIO()
            env_df.to_csv(buf, index=False, encoding="euc-kr")
            zf.writestr(f"env_{crop_ko}_{year}.csv", buf.getvalue())

            logger.info("  [%d] %s 생육 데이터 생성 중...", year, crop_ko)
            growth_df = _make_growth_df(crop_ko, cfg, year)
            if len(growth_df) == 0:
                continue
            buf2 = io.BytesIO()
            growth_df.to_csv(buf2, index=False, encoding="euc-kr")
            zf.writestr(f"growth_{crop_ko}_{year}.csv", buf2.getvalue())

    logger.info("  ✅ %s 생성 완료 (%.1f MB)", zip_path.name, zip_path.stat().st_size / 1_048_576)
    return zip_path


# ── 모드: check ───────────────────────────────────────────────────────────────

def mode_check():
    """DATA_DIR 경로 존재 여부 및 파일 목록 출력."""
    from models.crop_config import DATA_DIR
    print(f"\n{'='*60}")
    print(f"DATA_DIR: {DATA_DIR}")
    print(f"{'='*60}")
    if DATA_DIR.exists():
        zips = list(DATA_DIR.glob("스마트팜_*.zip"))
        print(f"✅ 경로 존재. ZIP 파일 {len(zips)}개:")
        for z in sorted(zips):
            sz = z.stat().st_size / 1_048_576
            print(f"   {z.name}  ({sz:.1f} MB)")
    else:
        print(f"❌ 경로 없음: {DATA_DIR}")
        print("\n💡 해결 방법:")
        print("  1. 합성 데이터 생성:")
        print("     python scripts/setup_training_data.py --mode synthetic")
        print()
        print("  2. 실제 데이터 경로 재지정:")
        print("     python scripts/setup_training_data.py --mode patch --data-path <경로>")
        print()
        print("  3. crop_config.py 직접 수정:")
        print(f"     DATA_DIR 변수를 실제 ZIP 파일이 있는 경로로 변경")
    print()


# ── 모드: synthetic ───────────────────────────────────────────────────────────

def mode_synthetic(target_dir: Optional[Path] = None):
    """합성 데이터 생성 후 DATA_DIR에 배치."""
    from models.crop_config import DATA_DIR
    dest = target_dir or DATA_DIR
    dest.mkdir(parents=True, exist_ok=True)

    print(f"\n합성 데이터 생성 시작 — 대상 디렉토리: {dest}")
    print(f"연도: {YEARS_SYNTHETIC}, 작목: {list(CROPS_CONFIG.keys())}")
    print("(실제 농진청 데이터와 분포가 다를 수 있으므로 모델 성능은 제한적)")
    print()

    for year in YEARS_SYNTHETIC:
        logger.info("[%d] ZIP 생성 중...", year)
        create_zip(year, dest)

    # 완료 후 캐시 무효화
    cache_dir = ROOT / ".cache" / "training"
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir)
        logger.info("  기존 학습 캐시 삭제 (.cache/training/)")

    print(f"\n✅ 합성 데이터 생성 완료: {dest}")
    print("다음 단계:")
    print("  python scripts/train_stage1_growth.py --crop all")
    print("  python scripts/train_stage2_yield.py  --crop all")
    print()


# ── 모드: patch ───────────────────────────────────────────────────────────────

def mode_patch(data_path: str):
    """crop_config.py의 DATA_DIR를 지정된 경로로 패치."""
    new_path = Path(data_path).resolve()
    if not new_path.exists():
        print(f"❌ 지정 경로가 존재하지 않습니다: {new_path}")
        sys.exit(1)

    config_file = ROOT / "models" / "crop_config.py"
    text = config_file.read_text(encoding="utf-8")

    # DATA_DIR 라인 교체
    import re
    new_line = f'DATA_DIR = Path(r"{new_path}")'
    text2 = re.sub(
        r'^DATA_DIR\s*=.*$',
        new_line,
        text,
        flags=re.MULTILINE,
    )
    if text2 == text:
        print("⚠️  DATA_DIR 패치 실패 — crop_config.py에서 DATA_DIR 라인을 찾지 못했습니다.")
        sys.exit(1)

    config_file.write_text(text2, encoding="utf-8")
    print(f"✅ crop_config.py DATA_DIR 패치 완료:")
    print(f"   {new_line}")
    print()
    # 캐시 무효화
    cache_dir = ROOT / ".cache" / "training"
    if cache_dir.exists():
        import shutil
        shutil.rmtree(cache_dir)
        print("  기존 학습 캐시 삭제 (.cache/training/)")


# ── 모드: env ─────────────────────────────────────────────────────────────────

def mode_env():
    """현재 Python 환경 및 의존성 체크."""
    print("\n패키지 버전 체크:")
    packages = ["numpy", "pandas", "sklearn", "xgboost", "lightgbm", "shap", "optuna", "mlflow"]
    for pkg in packages:
        try:
            mod = __import__(pkg if pkg != "sklearn" else "sklearn")
            ver = getattr(mod, "__version__", "?")
            print(f"  ✅ {pkg:12s} {ver}")
        except ImportError:
            print(f"  ❌ {pkg:12s} 미설치")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="스마트팜 훈련 데이터 설정")
    parser.add_argument("--mode", choices=["check", "synthetic", "patch", "env"],
                        default="check",
                        help="실행 모드 (check|synthetic|patch|env)")
    parser.add_argument("--data-path", type=str, default=None,
                        help="patch 모드 시 새 DATA_DIR 경로")
    parser.add_argument("--dest", type=str, default=None,
                        help="synthetic 모드 시 생성 위치 (기본: DATA_DIR)")
    args = parser.parse_args()

    if args.mode == "check":
        mode_check()
    elif args.mode == "synthetic":
        dest = Path(args.dest) if args.dest else None
        mode_synthetic(dest)
    elif args.mode == "patch":
        if not args.data_path:
            print("❌ --data-path 를 지정하세요.")
            parser.print_help()
            sys.exit(1)
        mode_patch(args.data_path)
    elif args.mode == "env":
        mode_env()
