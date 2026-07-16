"""교재 [별첨1] 작목별 스마트팜 환경 제어값 기준표 — 추출·검증.

★ 왜 검증이 필요한가:
  원본 PDF(HWP → "Microsoft: Print To PDF")의 텍스트 레이어가 일부 손상돼 있다.
  단어 좌표로 확인한 결과 '16~218℃'·'22~225℃' 가 **단일 텍스트 런**으로 존재한다
  (병합 아티팩트가 아니라 원본이 그렇다). 218℃ 는 농학적으로 불가능하므로 추출로
  복구할 수 없다. 잘못된 온도 기준이 지식베이스에 들어가면 농가가 잘못된 환경으로
  재배하게 되므로, 값을 추측하지 않고 '검증 필요'로 표시한다.

판정 규칙(도메인 상식 기반 범위 검사):
  온도 5~40℃ / 습도 30~95% / CO₂ 300~2000ppm / 광량 50~1500 / EC 0.3~6.0 / pH 4.0~8.0
  범위를 벗어나거나 파싱 불가하면 status='needs_review'.

사용:
  python scripts/validate_env_table.py            # 검증 리포트
  python scripts/validate_env_table.py --write    # out/kb_env_table.json 저장(검증본만 ok)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "outputs" / "스마트농업컨설턴트 교재_250630.pdf"
OUT = ROOT / "out" / "kb_env_table.json"

# (min, max) 허용 범위 — 이 밖이면 손상으로 간주
BOUNDS = {
    "temp_day":  (5, 40), "temp_night": (5, 40),
    "humidity":  (30, 95), "co2": (300, 2000),
    "par":       (50, 1500), "ec": (0.3, 6.0), "ph": (4.0, 8.0),
}
COL = ["stage", "temp", "humidity", "co2", "par", "ec", "ph"]


def _rng(s: str):
    """'24~26' → (24.0, 26.0). 파싱 불가 시 None."""
    if not s:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)", s.replace("\n", ""))
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def _ok(rng, key):
    if not rng:
        return False
    lo, hi = BOUNDS[key]
    a, b = rng
    return lo <= a <= hi and lo <= b <= hi and a <= b


def extract() -> list[dict]:
    import fitz
    d = fitz.open(PDF)
    rows: list[dict] = []
    for pno in (447, 448):
        pg = d[pno]
        # 작목 제목(예: '1. 토마토 (대과)')을 y 순으로 수집해 표와 매칭
        titles = []
        for ln in pg.get_text(sort=True).split("\n"):
            if (m := re.match(r"^\s*(\d)\.\s*([가-힣]{2,10})", ln)):
                titles.append(m.group(2))
        for ti, tb in enumerate(pg.find_tables().tables):
            crop = titles[ti] if ti < len(titles) else f"p{pno+1}_t{ti+1}"
            for r in tb.extract()[1:]:               # 헤더 제외
                cells = [(c or "").replace("\n", "") for c in r]
                if len(cells) < 7 or not cells[0].strip():
                    continue
                temp = cells[1]
                day, night = (temp.split("/") + [""])[:2]
                rec = {
                    "crop": crop, "stage": cells[0].strip(),
                    "page": pno + 1,
                    "raw": {"temp": temp, "humidity": cells[2], "co2": cells[3],
                            "par": cells[4], "ec": cells[5], "ph": cells[6]},
                    "parsed": {
                        "temp_day": _rng(day), "temp_night": _rng(night),
                        "humidity": _rng(cells[2]), "co2": _rng(cells[3]),
                        "par": _rng(cells[4]), "ec": _rng(cells[5]), "ph": _rng(cells[6]),
                    },
                }
                bad = [k for k, v in rec["parsed"].items() if not _ok(v, k)]
                rec["bad_fields"] = bad
                rec["status"] = "ok" if not bad else "needs_review"
                rows.append(rec)
    d.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    rows = extract()
    ok = [r for r in rows if r["status"] == "ok"]
    ng = [r for r in rows if r["status"] != "ok"]
    print(f"총 {len(rows)}행 (작목 {len({r['crop'] for r in rows})}종) | "
          f"정상 {len(ok)} · 검증필요 {len(ng)}")

    print("\n=== 검증 필요 행(원본 손상 의심 — 값을 추측하지 않음) ===")
    for r in ng:
        print(f"  {r['crop']:<8}{r['stage']:<8} p{r['page']}  손상필드={','.join(r['bad_fields'])}")
        print(f"      raw temp = {r['raw']['temp']!r}")

    print("\n=== 정상 행 샘플 ===")
    for r in ok[:4]:
        p = r["parsed"]
        print(f"  {r['crop']:<8}{r['stage']:<8} 주{p['temp_day']} 야{p['temp_night']} "
              f"습{p['humidity']} CO₂{p['co2']} EC{p['ec']}")

    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": "스마트농업컨설턴트 교재(2025-06-30) [별첨1] 작목별 스마트팜 환경 제어값 기준표",
            "copyright": "㈜이암허브·한국스마트농업AI협회",
            "warning": "원본 PDF 텍스트 레이어 일부 손상(예: '16~218℃'). needs_review 행은 "
                       "원본 HWP 또는 사람 확인 전까지 사용 금지.",
            "rows": rows,
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {OUT} ({OUT.stat().st_size:,} bytes)")
    else:
        print("\n(리포트 — 저장하려면 --write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
