# -*- coding: utf-8 -*-
"""노지 표준재배력 SSOT 로더 — models/cultivation_calendar.json.

정직화 원칙:
  · 시기/기준은 source 있는 값만 노출. 미적재 작목은 available:false(창작 폴백 금지).
  · 품종/날짜 세밀 해상도는 외부 표준재배력이 적재된 작목만(현 seed는 crop_config 작형월
    기반 coarse). 정밀 재배력 승격은 docs/cultivation_calendar_sources.md 참조.
  · 이번 달 평년 기후는 ERA5(climatology) 실측 근거로 병합.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

_PATH = Path(__file__).resolve().parent / "cultivation_calendar.json"
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def list_supported() -> list:
    """표준재배력이 적재된 작목 목록."""
    return [k for k in _load().keys() if not k.startswith("_")]


def get_calendar(crop_ko: str, variety: Optional[str] = None,
                 month: Optional[int] = None) -> dict:
    """작목(·품종·월) 표준재배력 반환. 미적재 시 available:false(정직 폴백)."""
    data = _load()
    ck = (crop_ko or "").strip()
    crop = data.get(ck)
    if not crop:  # '감귤(노지온주)' 등 접미사 정규화
        base = ck.split("(")[0].split(" ")[0].strip()
        crop = data.get(base)
        if crop:
            ck = base
    if not crop:
        return {"available": False, "crop_ko": crop_ko,
                "reason": f"'{crop_ko}' 표준재배력 미적재", "supported": list_supported()}
    varieties = crop.get("varieties", {})
    vk = variety if (variety and variety in varieties) else next(iter(varieties), None)
    v = varieties.get(vk, {}) if vk else {}
    out = {
        "available": True, "crop_ko": ck, "crop_en": crop.get("crop_en"),
        "crop_type": crop.get("crop_type"), "region": crop.get("region"),
        "source": crop.get("source"),
        "variety": vk, "varieties": list(varieties.keys()),
        "sow_transplant": v.get("sow_transplant"), "harvest": v.get("harvest"),
        "season_months": v.get("season_months"), "note": v.get("note"),
        "meta": data.get("_meta", {}),
    }
    if month is not None:
        mm = int(month)
        out["month"] = mm
        sow = (v.get("sow_transplant") or {}).get("months") or []
        harv = (v.get("harvest") or {}).get("months") or []
        out["phase_now"] = ("수확기" if mm in harv else
                            "파종·정식기" if mm in sow else
                            "생육·관리기" if mm in (v.get("season_months") or []) else "작기 외")
        # 이번 달 평년 기후(ERA5) 실측 근거 병합
        try:
            from api.services.climatology import get_climatology
            out["climate_normal"] = get_climatology(ck, mm)
        except Exception:
            out["climate_normal"] = None
    return out
