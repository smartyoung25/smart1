# -*- coding: utf-8 -*-
"""장기(16일) 기상예보 어댑터 — Open-Meteo (무료·키 불필요).

기상청 단기/중기(~10일) 한계를 넘는 14~16일 일별 예보를 제공.
농업 변수(ET₀·일사·강수·기온·풍속) 포함 → P1~P6 관수 의사결정 입력.
캐시 6시간(파일). 호출 실패 시 None → 상위에서 KMA/계절 폴백.
"""
from __future__ import annotations
import json, time, urllib.request, urllib.parse
from pathlib import Path
from typing import Optional

_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "ext_weather"
_TTL = 6 * 3600  # 6시간

# 시군구/시도 → 대표 좌표 (없으면 한국 중심)
_COORDS = {
    "창녕군": (35.54, 128.49), "진주시": (35.18, 128.11), "밀양시": (35.50, 128.75),
    "제주시": (33.50, 126.53), "서귀포시": (33.25, 126.56), "부여군": (36.28, 126.91),
    "논산시": (36.19, 127.10), "상주시": (36.41, 128.16), "안동시": (36.57, 128.73),
    "나주시": (35.02, 126.71), "김제시": (35.80, 126.88), "정읍시": (35.57, 126.86),
    "화성시": (37.20, 126.83), "이천시": (37.27, 127.43), "춘천시": (37.88, 127.73),
    "수원시": (37.26, 127.03), "대구": (35.87, 128.60), "광주": (35.16, 126.85),
}
_SIDO_FALLBACK = {
    "경상남도": (35.4, 128.2), "경상북도": (36.3, 128.7), "전라남도": (34.9, 126.9),
    "전라북도": (35.7, 127.1), "충청남도": (36.5, 126.8), "충청북도": (36.8, 127.7),
    "경기도": (37.4, 127.2), "강원도": (37.8, 128.2), "제주특별자치도": (33.4, 126.5),
    "제주도": (33.4, 126.5),
}

def _coords(sido: str, sigungu: str) -> tuple[float, float]:
    if sigungu in _COORDS: return _COORDS[sigungu]
    for k, v in _COORDS.items():
        if sigungu and (k[:-1] in sigungu or sigungu in k): return v
    return _SIDO_FALLBACK.get(sido, (36.5, 127.8))  # 한국 중심 폴백

def _cache_path(lat: float, lon: float) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{lat:.2f}_{lon:.2f}.json"

def get_extended_forecast(sido: str = "", sigungu: str = "", days: int = 16) -> Optional[dict]:
    days = max(1, min(16, int(days)))
    lat, lon = _coords(sido or "", sigungu or "")
    cp = _cache_path(lat, lon)
    # 캐시
    if cp.exists() and (time.time() - cp.stat().st_mtime) < _TTL:
        try: return json.loads(cp.read_text(encoding="utf-8"))
        except Exception: pass
    # Open-Meteo 호출
    qs = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "Asia/Seoul", "forecast_days": days,
        "daily": ",".join([
            "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
            "precipitation_probability_max", "et0_fao_evapotranspiration",
            "shortwave_radiation_sum", "wind_speed_10m_max", "weather_code",
        ]),
    })
    try:
        raw = json.loads(urllib.request.urlopen(
            f"https://api.open-meteo.com/v1/forecast?{qs}", timeout=12).read())
        dy = raw.get("daily", {}); t = dy.get("time", [])
        items = []
        for i in range(len(t)):
            items.append({
                "date": t[i],
                "t_max": dy["temperature_2m_max"][i], "t_min": dy["temperature_2m_min"][i],
                "rain_mm": dy["precipitation_sum"][i], "rain_prob": (dy.get("precipitation_probability_max") or [None]*len(t))[i],
                "et0": dy["et0_fao_evapotranspiration"][i], "solar_mj": dy["shortwave_radiation_sum"][i],
                "wind_max": dy["wind_speed_10m_max"][i], "wcode": dy["weather_code"][i],
            })
        # 재해 경보 플래그(농업): 강풍·강우·고온·무강우건조
        alerts = []
        for it in items:
            if it["wind_max"] and it["wind_max"] >= 32.4: alerts.append((it["date"], "강풍", it["wind_max"]))
            if it["rain_mm"] and it["rain_mm"] >= 30: alerts.append((it["date"], "호우", it["rain_mm"]))
            if it["t_max"] and it["t_max"] >= 33: alerts.append((it["date"], "폭염", it["t_max"]))
            if it["t_min"] is not None and it["t_min"] <= 0: alerts.append((it["date"], "서리/저온", it["t_min"]))
        out = {
            "source": "open-meteo", "lat": lat, "lon": lon, "days": len(items),
            "region": f"{sido} {sigungu}".strip() or "한국",
            "items": items,
            "summary": {
                "avg_et0": round(sum(x["et0"] for x in items if x["et0"] is not None) / max(len(items), 1), 2),
                "total_rain": round(sum(x["rain_mm"] for x in items if x["rain_mm"] is not None), 1),
                "max_temp": max((x["t_max"] for x in items if x["t_max"] is not None), default=None),
            },
            "hazards": [{"date": d, "type": k, "value": v} for d, k, v in alerts][:8],
        }
        try: cp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except Exception: pass
        return out
    except Exception:
        return None
