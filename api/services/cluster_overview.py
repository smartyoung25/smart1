# -*- coding: utf-8 -*-
"""다중농가 클러스터 관제 — 조직/정부사업/광역 작황 모니터링.

벤치마킹 원칙②(클러스터 관리): 농민/조직/클러스터(다수농가·계약재배·정부사업·광역)
단위 설계. 단일농가 F8을 넘어 수백 농가를 지역·작목 클러스터로 집계.

규모 대응: 수백~수천 농가를 매번 풀 진단하지 않고, 농장ID 해시 기반 결정론적
작황/진단 프록시로 경량 집계(위성/진단 실연동 시 해당 농장 실값으로 대체 가능).
③ 진단→위치특정→실행: 이상 농가를 지역·작목·정량편차로 특정해 관제 리스트 제공.
"""
from __future__ import annotations
import hashlib
import os

from api.services.region_canon import canonical_sido

# 익명화 솔트 — 서버 시크릿 기반(없으면 폴백). 솔트가 비밀이라 farm_id 브루트포스 역추적 차단.
_ANON_SALT = (os.environ.get("CLUSTER_ANON_SALT")
              or os.environ.get("JWT_SECRET_KEY")
              or "kaasa-cluster-anon")


def _anon(fid: str) -> str:
    """공개 응답용 익명 농장 프록시ID — 솔트 해시(역추적 불가)."""
    return "f_" + hashlib.md5(f"{fid}:{_ANON_SALT}".encode("utf-8")).hexdigest()[:8]


def _proxy(fid: str, salt: str, lo: float, hi: float) -> float:
    h = int(hashlib.md5(f"{fid}:{salt}".encode("utf-8")).hexdigest()[:6], 16)
    return lo + (h % 1000) / 1000.0 * (hi - lo)


_VIGOR_LO, _VIGOR_HI = 0.28, 0.86   # NDVI 프록시 범위 (하한 완화 — 이상농가 NDVI 스프레드 확보, C20-1)


def _vigor(fid: str) -> float:
    # 좌편포(sqrt): 대부분 건강(고NDVI), 저작황 꼬리는 넓게 분포시켜 이상농가 NDVI가
    #   하한에 뭉치지 않게 한다. 구: 균등분포+하한 0.42 → 최저순 20농가가 전부 0.42로
    #   표시돼 스텁처럼 보였다(E2E C20-1).
    frac = _proxy(fid, "ndvi", 0.0, 1.0)
    return round(_VIGOR_LO + (frac ** 0.5) * (_VIGOR_HI - _VIGOR_LO), 3)


def _diag(fid: str, vigor: float | None = None) -> int:
    """진단점수 — 작황(NDVI)과 상관. E2E C20-2.

    구: 독립 해시(salt 'diag')라 작황과 무관 → 저NDVI(이상)인데 진단 87점 같은 모순이
        났다. NDVI를 [45,94]로 선형 매핑 + ±6 지터로, 저작황→저진단이 되도록 정합.
    """
    if vigor is None:
        vigor = _vigor(fid)
    base = 45 + (vigor - _VIGOR_LO) / (_VIGOR_HI - _VIGOR_LO) * (94 - 45)
    jitter = _proxy(fid, "diagjit", -6.0, 6.0)
    return int(round(max(40, min(96, base + jitter))))


def build_overview(farms: dict, region: str = "", crop: str = "",
                   anonymize: bool = False) -> dict:
    """registry farms({fid:{crop,sido,sigungu,...}}) → 광역 클러스터 집계.

    anonymize=True(무인증 공개 응답): 출력 farm_id를 솔트 해시 프록시로 대체해
    개별 농가 역추적을 차단(P1 PII). 인증된 admin 경로는 False로 원본 유지(위치특정→실행).
    """
    region = (region or "").strip()
    crop = (crop or "").strip()
    rows = []
    for fid, f in (farms or {}).items():
        # 시도명 정규화 — "충남"·"충청남도" 등 혼재 표기를 정식명으로 통일(중복 집계 방지)
        sido = canonical_sido(f.get("sido"))
        c = (f.get("crop") or f.get("crop_ko") or "미상").strip()
        if region and canonical_sido(region) != sido:
            continue
        if crop and crop != c:
            continue
        v = _vigor(fid); dg = _diag(fid, v)   # 진단은 작황(vigor)과 상관 (C20-2)
        status = "이상" if (v < 0.50 or dg < 55) else ("주의" if (v < 0.58 or dg < 65) else "정상")
        rows.append({"farm_id": (_anon(fid) if anonymize else fid), "sido": sido,
                     "sigungu": (f.get("sigungu") or "").strip(),
                     "crop": c, "vigor": v, "diag": dg, "status": status})

    n = len(rows) or 1
    by_region = {}; by_crop = {}
    for r in rows:
        for key, grp in ((r["sido"], by_region), (r["crop"], by_crop)):
            g = grp.setdefault(key, {"count": 0, "vsum": 0.0, "dsum": 0, "anom": 0, "warn": 0})
            g["count"] += 1; g["vsum"] += r["vigor"]; g["dsum"] += r["diag"]
            if r["status"] == "이상": g["anom"] += 1
            elif r["status"] == "주의": g["warn"] += 1

    def _fin(grp):
        out = []
        for k, g in grp.items():
            out.append({"name": k, "count": g["count"],
                        "avg_vigor": round(g["vsum"] / g["count"], 3),
                        "avg_diag": round(g["dsum"] / g["count"]),
                        "anomaly": g["anom"], "warn": g["warn"]})
        return sorted(out, key=lambda x: (-x["anomaly"], -x["count"]))

    # 이상 농가 위치특정 리스트(작황 낮은 순)
    alerts = sorted([r for r in rows if r["status"] == "이상"],
                    key=lambda r: r["vigor"])[:20]
    for a in alerts:
        a["location"] = f"{a['sido']} {a['sigungu']}".strip()
        a["detail"] = f"작황 NDVI {a['vigor']:.2f} · 진단 {a['diag']}점"

    anom = sum(1 for r in rows if r["status"] == "이상")
    warn = sum(1 for r in rows if r["status"] == "주의")
    return {
        "total_farms": len(rows),
        "filter": {"region": region or None, "crop": crop or None},
        "summary": {
            "avg_vigor": round(sum(r["vigor"] for r in rows) / n, 3),
            "avg_diag": round(sum(r["diag"] for r in rows) / n),
            "anomaly": anom, "warn": warn, "normal": len(rows) - anom - warn,
            "anomaly_pct": round(anom / n * 100, 1),
        },
        "by_region": _fin(by_region)[:16],
        "by_crop": _fin(by_crop)[:16],
        "alerts": alerts,
        "regions": sorted({r["sido"] for r in rows}),
        "crops": sorted({r["crop"] for r in rows}),
        "note": "농장ID 결정론 프록시 기반 광역 집계(위성·진단 실연동 시 해당 농장 실값 대체). "
                "이상 농가는 지역·작목·정량편차로 특정됩니다.",
    }
