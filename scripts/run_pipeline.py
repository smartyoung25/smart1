"""전체 4-Stage 파이프라인 오케스트레이션.

학습 의존성:
  Stage 1 & Stage 4 → 독립 (병렬 가능)
  Stage 2           → Stage 1 아티팩트 선택적 활용
  Stage 3           → Stage 2 완료 후 실행

실행:
  python scripts/run_pipeline.py --crop 딸기 --stage all
  python scripts/run_pipeline.py --crop all  --stage all
  python scripts/run_pipeline.py --crop 딸기 --stage 2
  python scripts/run_pipeline.py --crop all  --stage 4   # 비용 파라미터만
  python scripts/run_pipeline.py --crop 딸기 --validate  # 검증만
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from models.crop_config import CROP_CONFIGS, get_artifact_dir


def run_stage(stage: int, crop_ko: str) -> dict | None:
    """지정 Stage 실행."""
    if stage == 1:
        from scripts.train_stage1_growth import run_crop
    elif stage == 2:
        from scripts.train_stage2_yield import run_crop
    elif stage == 3:
        from scripts.train_stage3_revenue import run_crop
    elif stage == 4:
        from scripts.train_stage4_cost import main as run_cost
        run_cost([crop_ko])
        return {"stage": 4, "crop_ko": crop_ko, "done": True}
    else:
        logger.error("잘못된 stage: %d", stage)
        return None

    return run_crop(crop_ko)


def validate_pipeline(crop_ko: str) -> dict:
    """파이프라인 통합 검증 — 각 Stage 메타 로드 후 요약."""
    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        return {"error": f"지원하지 않는 작목: {crop_ko}"}

    art_dir = get_artifact_dir(config.crop_en)
    summary = {"crop_ko": crop_ko, "stages": {}}

    for stage, fname in [(1, "stage1_meta.json"), (2, "stage2_meta.json"),
                          (3, "stage3_meta.json")]:
        p = art_dir / fname
        if p.exists():
            meta = json.loads(p.read_text(encoding="utf-8"))
            summary["stages"][stage] = {
                "gate_passed": meta.get("gate_passed"),
                "cv_r2_mean":  meta.get("cv_r2_mean"),
                "mape":        meta.get("mape"),
                "n_train":     meta.get("n_train"),
            }
        else:
            summary["stages"][stage] = {"gate_passed": False, "note": "메타 없음"}

    # Stage 4: cost_seasonal.json 존재 여부
    cost_path = ROOT / "api" / "data" / "cost_seasonal.json"
    summary["stages"][4] = {
        "gate_passed": cost_path.exists(),
        "note": "cost_seasonal.json " + ("존재" if cost_path.exists() else "없음"),
    }

    all_passed = all(
        s.get("gate_passed", False)
        for s in summary["stages"].values()
    )
    summary["all_passed"] = all_passed

    # 출력
    logger.info("\n[%s] 파이프라인 검증 요약", crop_ko)
    for st, info in summary["stages"].items():
        status = "✅ PASS" if info.get("gate_passed") else "❌ FAIL"
        logger.info("  Stage %d: %s  r2=%.3f  mape=%.1f%%",
                    st, status,
                    info.get("cv_r2_mean") or 0,
                    info.get("mape") or 0)
    logger.info("  전체: %s", "✅ ALL PASS" if all_passed else "❌ FAIL")

    return summary


def build_pipeline_meta(crop_ko: str) -> None:
    """각 Stage 메타를 합산하여 pipeline_meta.json 갱신."""
    config = CROP_CONFIGS.get(crop_ko)
    if not config:
        return

    art_dir = get_artifact_dir(config.crop_en)
    meta = {"crop_ko": crop_ko, "crop_en": config.crop_en, "pipeline": "4stage"}

    for stage, fname in [(1, "stage1_meta.json"), (2, "stage2_meta.json"),
                          (3, "stage3_meta.json")]:
        p = art_dir / fname
        if p.exists():
            stage_meta = json.loads(p.read_text(encoding="utf-8"))
            meta[f"stage{stage}"] = stage_meta

    out_path = art_dir / "pipeline_meta.json"
    out_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("  pipeline_meta.json 저장: %s", out_path)


def main():
    parser = argparse.ArgumentParser(description="4-Stage 파이프라인 오케스트레이션")
    parser.add_argument("--crop",     default="all",
                        help="작목명 또는 'all'")
    parser.add_argument("--stage",    default="all",
                        help="실행 stage: 1|2|3|4|all")
    parser.add_argument("--validate", action="store_true",
                        help="학습 없이 검증만 실행")
    args = parser.parse_args()

    crops = list(CROP_CONFIGS.keys()) if args.crop == "all" else [args.crop]

    if args.validate:
        for crop in crops:
            validate_pipeline(crop)
        return

    stages = [1, 2, 3, 4] if args.stage == "all" else [int(args.stage)]

    logger.info("실행 대상: %s  Stage: %s", crops, stages)

    all_results = {}
    for crop in crops:
        all_results[crop] = {}
        for stage in stages:
            logger.info("\n▶ %s / Stage %d", crop, stage)
            r = run_stage(stage, crop)
            all_results[crop][stage] = r

        # pipeline_meta.json 갱신
        if set(stages) >= {1, 2, 3}:
            build_pipeline_meta(crop)

    # 최종 요약
    logger.info("\n" + "=" * 55)
    logger.info("4-Stage 파이프라인 실행 완료")
    logger.info("=" * 55)
    for crop in crops:
        validate_pipeline(crop)


if __name__ == "__main__":
    main()
