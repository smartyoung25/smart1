import json
from pathlib import Path

ARTS = Path("models/artifacts")
crops = {
    "감귤":"citrus","마늘":"garlic","무":"radish","양파":"onion","양배추":"headed_cabbage",
    "딸기":"strawberry","방울토마토":"cherry_tomato","완숙토마토":"tomato",
    "파프리카":"paprika","오이":"cucumber","참외":"melon",
}
print("=== 모델 파일 현황 ===")
for ko, en in crops.items():
    d = ARTS / en
    m2 = (d / "m2_meta.json").exists()
    m1 = (d / "m1_meta.json").exists()
    cand = (d / "candidate" / "m2_meta.json").exists()
    mape = "—"
    if m2:
        try:
            meta = json.loads((d / "m2_meta.json").read_text(encoding="utf-8"))
            v = meta.get("mape", meta.get("mape_cv", None))
            if v is not None:
                mape = f"{float(v):.1f}%"
        except Exception:
            pass
    print(f"  {ko:6s} ({en:15s}): M2={m2} M1={m1} cand={cand} MAPE={mape}")
