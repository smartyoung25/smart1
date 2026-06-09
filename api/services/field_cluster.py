# -*- coding: utf-8 -*-
"""노지 클러스터 작황 모니터링 — 무센서·위성/AI/기상 기반.

벤치마킹 원칙(사용자 지정):
  ① 무센서 광역관리 — 위성영상·AI·기상으로 개별 고가센서 없이 작물건강·스트레스·이상 모니터링
  ② 클러스터 관리 — 농민/조직/클러스터(다수농가·계약재배·정부사업·광역 작황) 단위 설계
  ③ 진단→위치특정→실행알림 — 단순 NDVI 표시가 아니라
     개인화 알림·목표위치·정량화된 편차(Δ)·실행 호출(현장확인 지시) 제공

데이터 정직성: 위성 API 미연동 시 식생지수는 결정론적 프록시(필지ID 해시 + 기상스트레스)로
생성하되 source='satellite-proxy'로 라벨. Sentinel-2/팜맵 연동 시 source='sentinel-2'로 실측 전환.
"""
from __future__ import annotations
import hashlib
from typing import Optional


def _seed_ndvi(key: str) -> float:
    """필지 식별자 → 결정론적 기준 NDVI(0.50~0.86). 위성 미연동 시 프록시."""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:6], 16)
    return round(0.50 + (h % 360) / 1000.0, 3)  # 0.50~0.86


def _weather_stress(region_wx: Optional[dict]) -> dict:
    """16일 기상 → 수분/고온 스트레스(무센서). extended_weather 출력 사용."""
    if not region_wx or not region_wx.get("items"):
        return {"water_stress_pct": 0, "heat_days": 0, "et0": None, "rain_mm": None,
                "note": "기상 데이터 없음 — 스트레스 보정 미적용", "source": "none"}
    items = region_wx["items"][:7]  # 향후 1주 누적
    et0 = sum((x.get("et0") or 0) for x in items)
    rain = sum((x.get("rain_mm") or 0) for x in items)
    heat_days = sum(1 for x in items if (x.get("t_max") or 0) >= 31)
    # 수분스트레스: 증발산이 강수보다 클수록 ↑ (0~40%)
    deficit = max(0.0, et0 - rain)
    water_stress = min(40, round(deficit / max(et0, 1) * 40))
    return {"water_stress_pct": water_stress, "heat_days": heat_days,
            "et0": round(et0, 1), "rain_mm": round(rain, 1),
            "note": f"7일 ET₀ {et0:.0f}mm·강수 {rain:.0f}mm → 수분스트레스 {water_stress}%·고온 {heat_days}일",
            "source": region_wx.get("source", "open-meteo")}


def _grade(v: float) -> str:
    return "우수" if v >= 0.70 else "보통" if v >= 0.55 else "주의"


def build_cluster(*, cluster_id: str, region: str, parcels: list,
                  region_wx: Optional[dict] = None, soil: Optional[dict] = None,
                  satellite_live: bool = False) -> dict:
    """클러스터 작황 종합 — 필지별 식생지수 + 편차 + 위치특정 이상 알림.

    parcels: [{name, crop, area_ha, ndvi?(실측), lat?, lon?}]
    region_wx: extended_weather.get_extended_forecast() 결과(무센서 스트레스)
    soil: /field/soil(흙토람) — 있으면 토양수분으로 NDVI 보정
    """
    stress = _weather_stress(region_wx)
    ws = stress["water_stress_pct"] / 100.0

    # 토양수분(있으면) → 필지별 보정 매핑(name→moisture)
    soil_moist = {}
    try:
        for s in ((soil or {}).get("parcels") or []):
            if s.get("name") is not None and s.get("moisture") is not None:
                soil_moist[s["name"]] = float(s["moisture"])
    except Exception:
        soil_moist = {}

    rows = []
    for i, p in enumerate(parcels):
        name = p.get("name") or f"{i+1}번 필지"
        if satellite_live and p.get("ndvi") is not None:
            ndvi = round(float(p["ndvi"]), 3)
        else:
            base = _seed_ndvi(f"{cluster_id}:{name}")
            # 기상 수분스트레스로 하향, 토양수분 높으면 소폭 상향
            adj = -0.12 * ws
            if name in soil_moist:
                adj += (soil_moist[name] - 55) / 500.0  # ±0.09 범위
            ndvi = round(max(0.20, min(0.92, base + adj)), 3)
        rows.append({"name": name, "crop": p.get("crop") or "-",
                     "area_ha": p.get("area_ha"), "ndvi": ndvi,
                     "lat": p.get("lat"), "lon": p.get("lon")})

    n = len(rows) or 1
    mean = round(sum(r["ndvi"] for r in rows) / n, 3)
    var = sum((r["ndvi"] - mean) ** 2 for r in rows) / n
    std = round(var ** 0.5, 3)

    # ③ 위치특정 이상 알림 — 클러스터 평균 대비 정량 편차(Δ%) + 실행 호출
    alerts = []
    for r in rows:
        dev_pct = round((r["ndvi"] - mean) / max(mean, 0.01) * 100, 1)
        r["vigor"] = _grade(r["ndvi"])
        r["deviation_pct"] = dev_pct
        r["status"] = "정상"
        sev = None; typ = None; action = None
        if r["ndvi"] < 0.50 or dev_pct <= -12:
            sev = "danger"; typ = "생육 저조"; action = "현장 확인·관수/시비 점검"; r["status"] = "이상"
        elif stress["water_stress_pct"] >= 25 and r["ndvi"] < mean:
            sev = "warn"; typ = "수분 스트레스"; action = "관개 우선 배정"; r["status"] = "주의"
        elif dev_pct <= -7:
            sev = "warn"; typ = "평균대비 편차"; action = "생육 추세 관찰"; r["status"] = "주의"
        if sev:
            alerts.append({
                "parcel": r["name"], "location": r["name"] + (f" ({r['crop']})" if r['crop'] != '-' else ''),
                "lat": r.get("lat"), "lon": r.get("lon"),
                "type": typ, "ndvi": r["ndvi"], "deviation_pct": dev_pct,
                "severity": sev, "action": action,
                "detail": f"NDVI {r['ndvi']:.2f} · 클러스터 평균 대비 {dev_pct:+.1f}%"
                          + (f" · {stress['note']}" if typ == '수분 스트레스' else ''),
                "target": "f5_remote.html", "record": "disease_check",
            })
    sev_rank = {"danger": 0, "warn": 1}
    alerts.sort(key=lambda a: (sev_rank.get(a["severity"], 2), a["deviation_pct"]))

    anomaly = sum(1 for r in rows if r["status"] == "이상")
    warn = sum(1 for r in rows if r["status"] == "주의")
    uniformity = max(0, round(100 - std * 250))  # 균일도(편차 작을수록↑)

    return {
        "cluster_id": cluster_id, "region": region or "-",
        "source": "sentinel-2" if satellite_live else "satellite-proxy",
        "parcel_count": len(rows),
        "total_area_ha": round(sum((r.get("area_ha") or 0) for r in rows), 2),
        "summary": {
            "mean_ndvi": mean, "std_ndvi": std, "uniformity_pct": uniformity,
            "vigor_grade": _grade(mean), "anomaly_count": anomaly, "warn_count": warn,
        },
        "weather_stress": stress,
        "parcels": rows,
        "alerts": alerts,
        "note": "위성 식생지수(미연동 시 프록시) + 16일 기상 스트레스 기반 무센서 작황진단. "
                "이상 필지는 위치·정량편차·실행지시로 제공됩니다.",
    }
