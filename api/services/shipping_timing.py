"""출하 시점 최적화 — 월별 실측 단가 기반.

연구개발계획서 과업②(다) "출하타이밍 최적화" 구현.

★ 무엇을 하나:
  매출 = 수확량 × 단가 인데, 단가는 계절성이 크다(실측: 딸기 10월 24,725원 vs
  6월 6,450원 = 3.8배 · 참외 1월 9,954 vs 7월 1,327 = 7.5배).
  수확량 예측이 부실해도 **단가는 시장 변수라 이력만으로 판단 가능**하므로,
  "언제 출하할까"는 지금 바로 답할 수 있다.

★ 데이터 출처(단일):
  api/data/price_stats.json 의 monthly_trend — 2018~2025 실측 거래 월별 집계
  (딸기 87,866건 등). 분위수(p25/median/p75)까지 있어 변동폭을 함께 제시한다.
  ※ KAMIS 일별 시세(api/data/real/kamis_*_daily.json)는 스케줄러 가동 후 누적분이라
    현재 18일치뿐 — 계절 판단에 못 쓴다. 현재가 참고용으로만 쓴다.

★ 정직성:
  · 표본수(n)를 함께 노출한다. 딸기 6월은 n=919 로 1월(8,980)의 1/10 이라 신뢰도가 낮다.
  · 저장성·품질 저하·수확 시기는 모델에 없다 — "단가만 보면" 이라는 전제를 명시한다.
    (딸기를 6월→10월로 미루는 건 물리적으로 불가능하다. 판단은 농가가 한다.)
  · 데이터 없는 월은 추정하지 않고 제외한다.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
_STATS_PATH = ROOT / "api" / "data" / "price_stats.json"

# 표본이 이보다 적은 월은 '신뢰도 낮음' 플래그
_N_MIN = 1000

_cache: dict | None = None


def _stats() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(_STATS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        # 조용히 비면 추천이 통째로 사라지므로 눈에 띄게 남긴다.
        logger.error("[shipping_timing] 가격 통계 없음(%s): %s", _STATS_PATH, e)
        _cache = {}
    return _cache


def _monthly(crop_ko: str) -> dict:
    mt = (_stats().get("monthly_trend") or {})
    # '완숙토마토' 처럼 정확 일치 우선, 없으면 부분 일치(농장 작목명이 길 수 있음)
    if crop_ko in mt:
        return mt[crop_ko]
    for k in mt:
        if k in (crop_ko or "") or (crop_ko or "") in k:
            return mt[k]
    return {}


def price_calendar(crop_ko: str) -> list[dict]:
    """월별 단가 달력. 데이터 없는 월은 제외(추정하지 않는다)."""
    m = _monthly(crop_ko)
    out = []
    for mm in range(1, 13):
        v = m.get(str(mm))
        if not v or not v.get("median_krw_kg"):
            continue
        n = int(v.get("n") or 0)
        out.append({
            "month": mm,
            "median": round(float(v["median_krw_kg"])),
            "p25": round(float(v.get("p25_krw_kg") or 0)) or None,
            "p75": round(float(v.get("p75_krw_kg") or 0)) or None,
            "n": n,
            "low_confidence": n < _N_MIN,
        })
    return out


def recommend(crop_ko: str, today: Optional[date] = None,
              horizon_months: int = 6) -> dict:
    """지금부터 horizon 개월 내 최적 출하월.

    ★ 단가만 본다. 저장성·수확기·품질은 판단하지 않는다(호출측이 농가에 명시할 것).
    """
    today = today or date.today()
    cal = price_calendar(crop_ko)
    if not cal:
        return {"crop": crop_ko, "available": False,
                "reason": "월별 단가 실측 데이터 없음 — 추천 불가"}

    by_month = {c["month"]: c for c in cal}
    cur = by_month.get(today.month)

    # 향후 horizon 개월(현재월 포함) 중 데이터가 있는 월만
    window = []
    for i in range(horizon_months):
        mm = (today.month - 1 + i) % 12 + 1
        c = by_month.get(mm)
        if c:
            window.append({**c, "months_ahead": i})
    if not window:
        return {"crop": crop_ko, "available": False,
                "reason": f"향후 {horizon_months}개월 단가 데이터 없음"}

    # ★ best 는 표본이 충분한 월에서만 고른다.
    #   구: median 최대만 봤다 → 극단적 이상치를 '최적'으로 추천했다.
    #   실측: 딸기 10월 24,725원(연중 최고)의 표본은 **24건** · 참외 1월 9,954원은 **22건**.
    #   거래 20여 건으로 "3.8배 비싸니 미루라"고 하면 농가를 잘못된 판단으로 이끈다.
    #   (앞서 모델 게이트에서 지적한 소표본 낙관편의와 같은 함정이다.)
    solid = [x for x in window if not x["low_confidence"]]
    best = max(solid, key=lambda x: x["median"]) if solid else None
    # 표본이 빈약해 제외된 고가 월 — 숨기지 않고 참고로 알린다
    excluded = sorted((x for x in window if x["low_confidence"] and
                       (best is None or x["median"] > best["median"])),
                      key=lambda x: -x["median"])

    # 연중 최고·최저 — 맥락 제공(여기도 표본 충분한 월만)
    cal_solid = [c for c in cal if not c["low_confidence"]] or cal
    peak = max(cal_solid, key=lambda x: x["median"])
    trough = min(cal_solid, key=lambda x: x["median"])

    if best is None:
        return {"crop": crop_ko, "available": False,
                "reason": (f"향후 {horizon_months}개월 중 표본이 충분한(n≥{_N_MIN}) 월이 없어 "
                           f"추천하지 않는다"),
                "calendar": cal}

    gain = None
    if cur and cur["median"] and not cur["low_confidence"]:
        gain = round((best["median"] - cur["median"]) / cur["median"] * 100, 1)

    return {
        "crop": crop_ko,
        "available": True,
        "today": today.isoformat(),
        "current": cur,
        "best": best,
        "gain_pct_vs_now": gain,
        # 표본 빈약으로 best 후보에서 제외한 고가 월 — 감추지 않고 근거와 함께 노출
        "excluded_low_confidence": [
            {"month": x["month"], "median": x["median"], "n": x["n"]} for x in excluded
        ],
        "window": window,
        "calendar": cal,
        "peak": {"month": peak["month"], "median": peak["median"]},
        "trough": {"month": trough["month"], "median": trough["median"]},
        "spread_ratio": (round(peak["median"] / trough["median"], 1)
                         if trough["median"] else None),
        "min_samples": _N_MIN,
        "source": "2018~2025 실측 거래 월별 집계(price_stats.monthly_trend)",
        # ★ 호출측이 반드시 사용자에게 전달해야 하는 한계
        "caveat": ("단가만 고려한 결과다. 저장성·품질 저하·수확 시기는 반영하지 않았다 — "
                   "출하를 미룰 수 있는지는 농가가 판단해야 한다."),
    }
