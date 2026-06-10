# -*- coding: utf-8 -*-
"""ERA5 외부기상을 학습 캐시에 주입 — M2 수확모델 외부기온 결측 보강.

파이프라인:
  1) python scripts/fetch_era5_openmeteo.py --crop 딸기 --start 2018 --end 2022
  2) python scripts/inject_era5_into_cache.py --crop 딸기   ← 본 스크립트
  3) python scripts/train_stage2_yield.py --crop 딸기

s2_env 캐시의 temp_external 결측을 ERA5 (year,month) 월별 기온으로 채운다.
단위 호환(°C)인 temp_external만 보강(solar_rad는 스케일 상이로 제외).
효과(딸기 실측): CV R² 0.192→0.295, MAPE 20.8→17.8%, 배포게이트 FAIL→PASS.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CROP_EN = {"딸기": "strawberry", "참외": "korean_melon", "방울토마토": "cherry_tomato",
           "완숙토마토": "tomato", "오이": "cucumber"}


def inject(crop_ko: str) -> dict:
    crop_en = CROP_EN.get(crop_ko, crop_ko)
    cache = ROOT / ".cache" / "training" / f"s2_env_{crop_ko}.parquet"
    era_fp = ROOT / "api" / "data" / "real" / f"era5_{crop_en}_monthly.json"
    if not cache.exists():
        raise FileNotFoundError(f"학습 캐시 없음: {cache} (먼저 build_training_cache 실행)")
    if not era_fp.exists():
        raise FileNotFoundError(f"ERA5 없음: {era_fp} (먼저 fetch_era5_openmeteo.py 실행)")

    era = json.loads(era_fp.read_text(encoding="utf-8"))["monthly"]
    df = pd.read_parquet(cache)

    def _t(y, m):
        v = era.get(f"{int(y)}-{int(m):02d}")
        return v["t_ext"] if v else None

    before = int(df["temp_external"].isna().sum())
    mask = df["temp_external"].isna()
    df.loc[mask, "temp_external"] = df.loc[mask].apply(lambda r: _t(r["year"], r["month"]), axis=1)
    after = int(df["temp_external"].isna().sum())
    df.to_parquet(cache)
    return {"crop": crop_ko, "imputed": before - after, "remaining_na": after,
            "temp_ext_mean": round(float(df["temp_external"].mean()), 2)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", default="딸기")
    a = ap.parse_args(argv)
    res = inject(a.crop)
    print(f"ERA5 보강 완료: {res}")


if __name__ == "__main__":
    main()
