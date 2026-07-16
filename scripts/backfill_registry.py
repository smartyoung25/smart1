"""models/registry.json 백필 — 권위 지표(stage2_meta) + gates 단일정책으로 정합화.

배경:
  registry.json 의 mape/cv_r2 는 재학습해도 갱신되지 않는 frozen 값이었고
  (딸기 v1~v8 이 전부 동일), gate_passed=False 인데 is_active=True 인 자기모순
  상태였다. 구 게이트(완화기준)의 잔재라 콘솔 버전이력·주간리포트가 틀린 값을 보였다.

이 스크립트는 각 작목의 **활성 버전 엔트리**를 다음으로 정합화한다:
  mape_stage2 / cv_r2 / n_train  ← models/artifacts/{crop}/stage2_meta.json (권위)
  verdict / gate_flags           ← pipeline.gates.evaluate_m2_gate
  gate_passed / is_active        ← verdict != fallback (register_version 과 동일 의미)
  active_version                 ← 폴백 판정이면 None (활성 모델 없음)

주의:
  · 서빙에는 영향이 없다 — model_loader/m2_yield 는 registry 를 참조하지 않고
    자체적으로 gates 판정을 수행한다. 이 백필은 기록·표시·롤백 정합용이다.
  · mape_stage3(매출)은 권위 출처가 없어 건드리지 않는다.
  · 기본은 dry-run. 실제 반영은 --apply.

사용:
  python scripts/backfill_registry.py            # 미리보기(변경 없음)
  python scripts/backfill_registry.py --apply    # 반영(.bak 백업 생성)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.gates import evaluate_m2_gate, read_stage2_metrics  # noqa: E402

REGISTRY = ROOT / "models" / "registry.json"
ARTIFACTS = ROOT / "models" / "artifacts"


def plan() -> tuple[dict, list]:
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    changes = []
    for crop_en, info in reg.items():
        versions = info.get("versions") or []
        if not versions:
            continue
        act_num = info.get("active_version")
        entry = next((v for v in versions if v.get("version") == act_num), None) \
            or next((v for v in versions if v.get("is_active")), None) \
            or versions[-1]

        auth = read_stage2_metrics(ARTIFACTS, crop_en)
        if auth.get("mape") is None:
            changes.append((crop_en, "권위 지표 없음 — 건너뜀", None))
            continue

        v = evaluate_m2_gate(auth.get("mape"), auth.get("cv_r2_mean"),
                             auth.get("n_train"), auth.get("train_r2"))
        before = {
            "mape_stage2": entry.get("mape_stage2"), "cv_r2": entry.get("cv_r2"),
            "gate_passed": entry.get("gate_passed"), "is_active": entry.get("is_active"),
            "active_version": info.get("active_version"),
        }
        after = {
            "mape_stage2": round(float(auth["mape"]), 4),
            "cv_r2": round(float(auth["cv_r2_mean"]), 4) if auth.get("cv_r2_mean") is not None else None,
            "gate_passed": v["serve_m2"], "is_active": v["serve_m2"],
            "active_version": (act_num if v["serve_m2"] else None),
        }
        # 실제 반영
        entry["mape_stage2"] = after["mape_stage2"]
        entry["cv_r2"] = after["cv_r2"]
        entry["n_train"] = auth.get("n_train")
        entry["verdict"] = v["verdict"]
        entry["gate_flags"] = v["flags"]
        entry["gate_passed"] = after["gate_passed"]
        entry["is_active"] = after["is_active"]
        for other in versions:
            if other is not entry:
                other["is_active"] = False
        info["active_version"] = after["active_version"]
        changes.append((crop_en, v["label"], (before, after, v)))
    return reg, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 반영(.bak 백업)")
    args = ap.parse_args()

    reg, changes = plan()
    print(f"{'작목':<15}{'판정':<10}{'MAPE(전→후)':<22}{'is_active(전→후)':<20}{'active_version'}")
    print("-" * 92)
    for crop, label, det in changes:
        if det is None:
            print(f"{crop:<15}{label}")
            continue
        b, a, v = det
        print(f"{crop:<15}{label:<10}"
              f"{str(b['mape_stage2']) + ' → ' + str(a['mape_stage2']):<22}"
              f"{str(b['is_active']) + ' → ' + str(a['is_active']):<20}"
              f"{str(b['active_version'])} → {str(a['active_version'])}")
        if v["flags"]:
            print(f"{'':<25}⚠ {'; '.join(v['flags'])}")

    if not args.apply:
        print("\n(dry-run — 변경 없음. 반영하려면 --apply)")
        return 0

    bak = REGISTRY.with_suffix(".json.bak")
    shutil.copy2(REGISTRY, bak)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n반영 완료. 백업: {bak.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
