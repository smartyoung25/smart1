"""교재 [별첨1] → climate_plan._RECOMMEND 형식(avg24·vpd) 변환.

배경:
  제품 _RECOMMEND 는 '딸기'만 고유값이고 방울토마토·완숙토마토·오이·파프리카·참외는
  전부 _default(동일한 일반값)를 쓴다. 교재 별첨1이 작목별·단계별 구체값을 제공하므로
  그 공백을 메운다.

★ 적용 범위(의도적으로 좁힘):
  · 딸기 = 제외 — 교재(일반재배)와 제품(겨울 촉성·야간저온 화아분화)이 활착기에서 5℃
    차이. 어느 쪽이 옳은지는 도메인 판단이라 덮어쓰지 않는다.
  · 참외 = 제외 — 교재 별첨1의 6번은 '멜론(Melon)'이며, 교재는 참외를 별개 작목으로
    다룬다("수박, 참외 등 포복성 작물"). 멜론 값을 참외에 넣으면 잘못된 기준이 된다.
  · 토마토 활착기 야간 / 생장기 주간 = 제외 — 원본 PDF 텍스트 손상('16~218℃').
  → 실제 적용: 방울토마토 · 오이 · 파프리카 · 완숙토마토(손상 단계 제외)

변환 방법(제품 공식 그대로 사용):
  avg24 = Σ(구간온도 × 구간시간) / 24   — PERIODS 가중(야간9·일출4·주간7·일몰전4)
          교재는 주/야 2값만 주므로: night·dawn←야간값, day·prenight←주간값으로 배정
  vpd   = climate_plan.vpd(temp, rh)    — 주간 온도·습도 기준(증산 최대 구간)
  범위는 교재의 하한/상한을 각각 넣어 [min, max] 밴드로 만든다.

사용:
  python scripts/build_crop_recommend.py           # 미리보기
  python scripts/build_crop_recommend.py --write   # out/kb_crop_recommend.json 저장
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.services.climate_plan import PERIODS, vpd  # noqa: E402

KB = ROOT / "out" / "kb_env_table.json"
OUT = ROOT / "out" / "kb_crop_recommend.json"

# 교재 작목 → 제품 작목 (검증된 매핑만)
CROP_MAP = {"토마토": "완숙토마토", "방울토마토": "방울토마토", "오이": "오이", "파프리카": "파프리카"}
# 제외: 딸기(전제 상충 — 보류) · 멜론(참외와 다른 작목)

STAGE_MAP = {"활착기": "establish", "생장기": "veg",
             "착과기": "flower", "개화·착과기": "flower",
             "수확기": "harvest", "성숙기": "harvest"}


def _hours() -> dict:
    h = {}
    for p in PERIODS:
        span = (p["to"] - p["from"]) % 24
        h[p["key"]] = span or 24
    return h


def avg24_from(day_t: float, night_t: float) -> float:
    """교재의 주/야 2값을 PERIODS 가중으로 24h 평균 환산(제품 공식과 동일 원리)."""
    h = _hours()
    temp = {"night": night_t, "dawn": night_t, "day": day_t, "prenight": day_t}
    tot = sum(h.values()) or 24
    return sum(temp[k] * v for k, v in h.items()) / tot


def build() -> dict:
    kb = json.loads(KB.read_text(encoding="utf-8"))
    out: dict = {}
    skipped: list[str] = []
    for r in kb["rows"]:
        crop = CROP_MAP.get(r["crop"])
        if not crop:
            skipped.append(f'{r["crop"]}/{r["stage"]}: 매핑 제외')
            continue
        stage = STAGE_MAP.get(r["stage"])
        if not stage:
            skipped.append(f'{r["crop"]}/{r["stage"]}: 단계 매핑 없음')
            continue
        if r["status"] != "ok":
            skipped.append(f'{r["crop"]}/{r["stage"]}: 원본 손상({",".join(r["bad_fields"])})')
            continue
        p = r["parsed"]
        d, n, rh = p["temp_day"], p["temp_night"], p["humidity"]
        lo = round(avg24_from(d[0], n[0]), 1)
        hi = round(avg24_from(d[1], n[1]), 1)
        # VPD: 주간 온도 × 습도. 습도 상한일 때 VPD 최소, 하한일 때 최대 → 밴드 뒤집힘 주의
        v1 = vpd(d[0], rh[1])
        v2 = vpd(d[1], rh[0])
        out.setdefault(crop, {"avg24": {}, "vpd": {}, "_src": {}})
        out[crop]["avg24"][stage] = [lo, hi]
        out[crop]["vpd"][stage] = [min(v1, v2), max(v1, v2)]
        out[crop]["_src"][stage] = {
            "page": r["page"], "stage_ko": r["stage"],
            "temp_day": d, "temp_night": n, "humidity": rh,
            "co2": p["co2"], "par": p["par"], "ec": p["ec"], "ph": p["ph"],
        }
    return {"recommend": out, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    res = build()
    rec = res["recommend"]
    print(f"적용 작목 {len(rec)}종: {', '.join(rec)}\n")
    for crop, v in rec.items():
        print(f"── {crop}")
        for st in ("establish", "veg", "flower", "harvest"):
            if st in v["avg24"]:
                s = v["_src"][st]
                print(f"   {st:<10}({s['stage_ko']:<7}) avg24={str(v['avg24'][st]):<14} "
                      f"vpd={str(v['vpd'][st]):<14} ← 주{s['temp_day']} 야{s['temp_night']} 습{s['humidity']}")
            else:
                print(f"   {st:<10}(—)       미적용")
    print("\n=== 제외 내역(추측하지 않은 것) ===")
    for s in res["skipped"]:
        print("  ·", s)

    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": "스마트농업컨설턴트 교재(2025-06-30) [별첨1]",
            "copyright": "㈜이암허브·한국스마트농업AI협회",
            "note": "딸기=보류(제품 겨울촉성 기준과 상충) · 참외=제외(교재는 멜론이며 참외와 다른 작목) "
                    "· 토마토 일부 단계=원본 손상으로 제외",
            **res,
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {OUT} ({OUT.stat().st_size:,} bytes)")
    else:
        print("\n(미리보기 — 저장하려면 --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
