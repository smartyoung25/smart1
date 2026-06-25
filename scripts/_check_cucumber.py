import json
from pathlib import Path
for en in ["cucumber", "citrus", "garlic"]:
    for fname in ["stage2_meta.json", "m2_meta.json", "pipeline_meta.json"]:
        p = Path(f"models/artifacts/{en}/{fname}")
        if p.exists():
            m = json.loads(p.read_text(encoding="utf-8"))
            print(f"{en}/{fname}: mape={m.get('mape','?')} r2={m.get('r2','?')} type={m.get('model_type','?')}")
