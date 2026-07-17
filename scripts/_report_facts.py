"""중간보고서에 들어갈 '사실'을 코드·아티팩트에서 뽑아 JSON 으로 덤프.

★ 왜: 보고서 수치를 손으로 적으면 코드와 조용히 어긋난다. 실제로 최초본은
  게이트 기준을 'CV R² ≥ 0.3 · n ≥ 60 필수'로 적었으나 코드는 0.20 이고 n 은
  하드 게이트가 아니라 경고 플래그였다 — 보고서 자체의 결과표(오이 n=30 인데
  '검증 적용')와도 모순됐다. 또 표4 수치를 registry.json(동결값)에서 인용해
  틀린 적이 있다 — 권위는 stage2_meta.json 뿐이다.

  그래서 게이트 임계·작목 판정·스택 규모를 전부 여기서 재도출한다.

사용:
  PYTHONPATH=C:/smart_farm python scripts/_report_facts.py
  → out/_report_facts.json
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.gates import (          # noqa: E402
    CV_R2_FALLBACK, CV_R2_MIN, MAPE_ADVISORY, N_MIN, OVERFIT_GAP,
    evaluate_crop, gate_mape, read_stage2_metrics,
)
from models.m2_yield import CROP_MAP  # noqa: E402

ARTS = ROOT / "models" / "artifacts"
OUT = ROOT / "out" / "_report_facts.json"

# 보고 대상 작목 — 시설 6종(표 순서는 판정 좋은 순)
CROPS = ["딸기", "오이", "파프리카", "완숙토마토", "방울토마토", "참외"]


# stage2_meta 의 model_type → 보고서 표기명
_MODEL_KO = {
    "lgb": "LightGBM",
    "xgb_lgb_ensemble": "XGBoost+LightGBM 앙상블",
    "ridge_fallback": "Ridge(폴백)",
}


def _model_of(en: str) -> str:
    """모델명은 stage2_meta.json 을 '직접' 읽는다.

    ★ read_stage2_metrics 를 쓰면 안 된다 — 그 함수는 _AUTH_KEYS(mape·cv_r2_mean·
      n_train·train_r2 등 지표)만 stage2_meta 로 덮어쓰고, model_type 은 base 인
      pipeline_meta(낡은 값)가 그대로 남는다. 실제로 딸기가 pipeline_meta 의
      'xgb_lgb_ensemble' 로 새어나왔으나 권위값은 'lgb' 다.
    """
    p = ARTS / en / "stage2_meta.json"
    if not p.exists():
        return "—"
    try:
        mt = json.loads(p.read_text(encoding="utf-8")).get("model_type")
    except Exception:
        return "—"
    return _MODEL_KO.get(mt, mt or "—")


def m2_table() -> list[dict]:
    rows = []
    for ko in CROPS:
        en = CROP_MAP.get(ko, ko)
        m = read_stage2_metrics(ARTS, en)
        d = evaluate_crop(ARTS, en)
        if m.get("cv_r2_mean") is None:
            print(f"  ! {ko}({en}) 검증지표(CV R²) 없음 — 표에서 제외")
            continue
        rows.append({
            "crop": ko, "crop_en": en,
            # ★ 보고서에는 교차검증 MAPE 를 싣는다. m["mape"] 는 학습값이라 보고 금지.
            "cv_mape": (round(float(gate_mape(m)), 1) if gate_mape(m) is not None else None),
            "train_mape": round(float(m["mape"]), 1),   # 진단용(보고서 본문에 쓰지 말 것)
            "cv_r2": (round(float(m["cv_r2_mean"]), 3) if m.get("cv_r2_mean") is not None else None),
            "n_train": m.get("n_train"),
            "model": _model_of(en),
            "verdict": d["verdict"], "label": d["label"],
            "reasons": d["reasons"], "flags": d["flags"],
        })
    return rows


def stack() -> dict:
    """플랫폼 규모 — 세지 말고 실제 파일에서 센다(보고서가 라우터 16개라 적었으나 15개였다)."""
    scr = len(list((ROOT / "screens").glob("*.html")))
    rtr = len([p for p in (ROOT / "api" / "routers").glob("*.py") if p.stem != "__init__"])
    svc = len([p for p in (ROOT / "api" / "services").glob("*.py") if p.stem != "__init__"])
    return {"screens": scr, "routers": rtr, "services": svc}


def kb() -> dict:
    d = ROOT / "api" / "data" / "kb"
    def n(f):
        p = d / f
        return len(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else 0
    tb, rl = n("kb_textbook_chunks.json"), n("kb_rules_chunks.json")
    return {"textbook": tb, "rules": rl, "total": tb + rl}


def farms() -> dict:
    """실증·학습 기반 농가 — farm_registry(농진청 수집분)에서 센다.

    ★ 이 716농가는 2018~2022 축적분이며, 2026년 2차년도 소득조사 20개소와는 별개다.
      보고서에서 섞어 쓰면 하지 않은 조사를 한 것처럼 보인다.
    """
    import collections
    p = ROOT / "api" / "data" / "farm_registry.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    recs = [v for v in (d.get("farms") or {}).values() if isinstance(v, dict)]
    by_crop = collections.Counter(v.get("crop") for v in recs)
    by_year = collections.Counter(str(v.get("year")) for v in recs if v.get("year"))
    return {
        "total": len(recs),
        "by_crop": dict(by_crop.most_common()),
        "years": sorted(by_year),
        "generated_at": d.get("generated_at"),
    }


def main() -> int:
    facts = {
        "generated": date.today().isoformat(),
        "report_month": f"{date.today():%Y. %m.}",
        "farms": farms(),
        # ★ 게이트는 CV R² 중심(2026-07-17 재편). MAPE 는 참고 지표다 —
        #   구 게이트는 학습(in-sample) MAPE 로 판정했다(딸기 학습 17.8% vs CV 107.3%).
        "gate": {
            "cv_r2_min": CV_R2_MIN, "cv_r2_fallback": CV_R2_FALLBACK,
            "mape_advisory": MAPE_ADVISORY, "n_min": N_MIN, "overfit_gap": OVERFIT_GAP,
        },
        "stack": stack(),
        "kb": kb(),
        "m2": m2_table(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")

    g, s, k = facts["gate"], facts["stack"], facts["kb"]
    print(f"게이트 : CV R²>={g['cv_r2_min']} 검증적용 · <={g['cv_r2_fallback']} 폴백 · "
          f"gap<={g['overfit_gap']} | 참고: CV MAPE>{g['mape_advisory']} 경보 · n<{g['n_min']} 소표본")
    print(f"스택   : 화면 {s['screens']} · 라우터 {s['routers']} · 서비스 {s['services']}")
    print(f"지식   : 교재 {k['textbook']} + 규칙 {k['rules']} = {k['total']}")
    print("M2 :")
    for r in facts["m2"]:
        print(f"  {r['crop']:<6} CV R² {str(r['cv_r2']):>7}  CV MAPE {str(r['cv_mape']):>6}%  "
              f"n={str(r['n_train']):>5}  {r['label']:<7} (학습MAPE {r['train_mape']})")
    print(f"\n저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
