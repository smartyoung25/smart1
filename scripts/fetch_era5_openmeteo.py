# -*- coding: utf-8 -*-
"""ERA5 재분석 기상 확보 — Open-Meteo Archive API (무키·무계정).

Copernicus CDS ERA5와 동일한 재분석 데이터를 Open-Meteo 아카이브로 인증 없이 수신.
대표 산지 좌표 × 연도 범위 → 월별 외부기상(기온·일사·강수·GDD) 집계 JSON 저장.
연도 간 환경 변동 신호 보강용(M2 수확모델 외부기상 결측 보완).

사용:
  python scripts/fetch_era5_openmeteo.py --crop 딸기 --start 2018 --end 2022
출력: api/data/real/era5_{crop_en}_monthly.json  {"(year,month)": {t_ext, solar_mj, rain_mm, gdd}}
"""
from __future__ import annotations
import argparse, json, time, urllib.request
from pathlib import Path

# 작물별 대표 산지 좌표(연도간 변동 포착 — 주산지 평균)
REGIONS = {
    "딸기": [  # 경남 진주·거창, 충남 논산, 전북 완주 (딸기 주산지)
        (35.18, 128.11, "경남 진주"), (35.69, 127.91, "경남 거창"),
        (36.19, 127.10, "충남 논산"), (35.84, 127.15, "전북 완주"),
    ],
    "참외": [  # 경북 성주(압도적 주산지)·칠곡, 충남 부여
        (35.92, 128.28, "경북 성주"), (35.99, 128.40, "경북 칠곡"),
        (36.28, 126.91, "충남 부여"),
    ],
    "방울토마토": [  # 충남 부여, 전남 담양, 경남 진주
        (36.28, 126.91, "충남 부여"), (35.32, 126.99, "전남 담양"),
        (35.18, 128.11, "경남 진주"),
    ],
    "완숙토마토": [  # 충남 논산, 전남 화순, 강원 화천(여름), 경북 상주
        (36.19, 127.10, "충남 논산"), (35.06, 126.99, "전남 화순"),
        (38.11, 127.71, "강원 화천"), (36.41, 128.16, "경북 상주"),
    ],
    "오이": [  # 충남 천안, 경기 평택, 경남 진주
        (36.81, 127.11, "충남 천안"), (36.99, 127.11, "경기 평택"),
        (35.18, 128.11, "경남 진주"),
    ],
}
CROP_EN = {"딸기": "strawberry", "참외": "korean_melon", "방울토마토": "cherry_tomato",
           "완숙토마토": "tomato", "오이": "cucumber"}
_GDD_BASE = 5.0   # 딸기 생육 기준온도(℃)


def _fetch(lat, lon, start, end):
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
           f"&start_date={start}-01-01&end_date={end}-12-31"
           "&daily=temperature_2m_mean,shortwave_radiation_sum,precipitation_sum"
           "&timezone=Asia%2FSeoul")
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read()).get("daily", {})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", default="딸기")
    ap.add_argument("--start", type=int, default=2018)
    ap.add_argument("--end", type=int, default=2022)
    a = ap.parse_args(argv)
    pts = REGIONS[a.crop]

    # (year,month) → 리스트 누적 후 평균
    acc = {}
    for lat, lon, name in pts:
        dy = _fetch(lat, lon, a.start, a.end)
        times = dy.get("time", [])
        for i, t in enumerate(times):
            y, m, _ = t.split("-")
            key = f"{y}-{int(m):02d}"
            d = acc.setdefault(key, {"t": [], "s": [], "r": [], "gdd": 0.0})
            tv = dy["temperature_2m_mean"][i]
            sv = dy["shortwave_radiation_sum"][i]
            rv = dy["precipitation_sum"][i]
            if tv is not None:
                d["t"].append(tv); d["gdd"] += max(0.0, tv - _GDD_BASE)
            if sv is not None: d["s"].append(sv)
            if rv is not None: d["r"].append(rv)
        time.sleep(0.3)  # API 예의
        print(f"  수신: {name} ({lat},{lon})")

    out = {}
    for key, d in sorted(acc.items()):
        npts = len(pts)
        out[key] = {
            "t_ext": round(sum(d["t"]) / len(d["t"]), 2) if d["t"] else None,
            "solar_mj": round(sum(d["s"]) / len(d["s"]), 2) if d["s"] else None,  # 일평균 일사
            "rain_mm": round(sum(d["r"]), 1) if d["r"] else None,                  # 월 누적(4지점합)
            "gdd": round(d["gdd"] / npts, 1),                                       # 지점평균 월 GDD
        }
    crop_en = CROP_EN.get(a.crop, a.crop)
    fp = Path(__file__).resolve().parents[1] / "api" / "data" / "real" / f"era5_{crop_en}_monthly.json"
    fp.write_text(json.dumps({"source": "open-meteo ERA5 archive (무키)",
                              "regions": [n for *_, n in pts], "crop": a.crop,
                              "monthly": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {fp}  ({len(out)} 개월)")
    sample = list(out.items())[36] if len(out) > 36 else list(out.items())[0]
    print("샘플:", sample)


if __name__ == "__main__":
    main()
