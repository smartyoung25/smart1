# -*- coding: utf-8 -*-
"""평년 기상 기준값(climatology) — ERA5 재분석 5년치(2018~2022) 월별 정규값.

scripts/fetch_era5_openmeteo.py 가 적재한 작물 주산지 ERA5(api/data/real/era5_*_monthly.json)를
달력월(01~12)별로 평균/표준편차 집계 → '평년 대비' 비교의 기준선 제공.
용도: 노지 작황·온실 에너지 계획에서 "이번 달이 평년 대비 더운가/흐린가" 판단.
"""
from __future__ import annotations
import json
import statistics as _st
from pathlib import Path
from typing import Optional

_REAL = Path(__file__).resolve().parents[1] / "data" / "real"
_CROP_EN = {"딸기": "strawberry", "참외": "korean_melon",
            "방울토마토": "cherry_tomato", "완숙토마토": "tomato",
            "오이": "cucumber", "파프리카": "paprika",
            # 제주·노지작물
            "감귤": "citrus", "월동무": "winter_radish", "당근": "carrot",
            "양배추": "cabbage", "마늘": "garlic", "양파": "onion",
            "배추": "napa_cabbage", "무": "radish", "대파": "welsh_onion"}
_cache: dict = {}


def _normals(crop_en: str) -> Optional[dict]:
    if crop_en in _cache:
        return _cache[crop_en]
    fp = _REAL / f"era5_{crop_en}_monthly.json"
    if not fp.exists():
        _cache[crop_en] = None
        return None
    raw = json.loads(fp.read_text(encoding="utf-8"))
    monthly = raw.get("monthly", {})
    # 달력월별 누적
    bym: dict = {f"{m:02d}": {"t": [], "s": [], "r": [], "g": []} for m in range(1, 13)}
    for key, v in monthly.items():
        mm = key.split("-")[1]
        if mm in bym:
            if v.get("t_ext") is not None:   bym[mm]["t"].append(v["t_ext"])
            if v.get("solar_mj") is not None: bym[mm]["s"].append(v["solar_mj"])
            if v.get("rain_mm") is not None:  bym[mm]["r"].append(v["rain_mm"])
            if v.get("gdd") is not None:      bym[mm]["g"].append(v["gdd"])

    def _agg(xs):
        if not xs:
            return None
        return {"mean": round(_st.mean(xs), 1),
                "min": round(min(xs), 1), "max": round(max(xs), 1),
                "std": round(_st.pstdev(xs), 1) if len(xs) > 1 else 0.0}

    out = {"crop_en": crop_en, "regions": raw.get("regions", []),
           "years": "2018~2022", "source": "ERA5(Open-Meteo archive)", "by_month": {}}
    for mm, d in bym.items():
        out["by_month"][mm] = {"t_ext": _agg(d["t"]), "solar_mj": _agg(d["s"]),
                               "rain_mm": _agg(d["r"]), "gdd": _agg(d["g"])}
    _cache[crop_en] = out
    return out


def get_climatology(crop_ko: str, month: int) -> dict:
    """작물·월의 평년 기준값 + 직전(현재 비교 가능하도록 mean) 반환."""
    ck = (crop_ko or "").strip()
    crop_en = _CROP_EN.get(ck)
    if not crop_en:   # 품종 접미사 등 정규화: '딸기(설향)'·'딸기 설향' → '딸기'
        base = ck.split("(")[0].split(" ")[0].strip()
        crop_en = _CROP_EN.get(base) or next((v for k, v in _CROP_EN.items() if k in ck), None)
    if not crop_en:
        return {"available": False, "reason": f"'{crop_ko}' ERA5 평년데이터 미보유",
                "supported": list(_CROP_EN.keys())}
    norm = _normals(crop_en)
    if not norm:
        return {"available": False, "reason": "ERA5 파일 없음"}
    mm = f"{int(month):02d}"
    cur = norm["by_month"].get(mm, {})
    return {"available": True, "crop_ko": crop_ko, "crop_en": crop_en,
            "month": int(month), "regions": norm["regions"],
            "years": norm["years"], "source": norm["source"],
            "normal": cur}
