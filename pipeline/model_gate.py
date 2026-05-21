"""모델 성능 게이트 + 자동 배포

신규 학습 아티팩트(candidate/)와 현행 모델(artifacts/)을 비교하여
MAPE/R² 개선 시 자동 교체, 기존 모델은 rollback/에 백업.

사용:
    python model_gate.py --crop 딸기 [--candidate_dir path] [--dry_run]

배포 기준 (하나라도 충족):
  - M2 MAPE 5%p 이상 감소
  - M1 R² 0.02 이상 증가

롤백:
  - artifacts/{crop}/prev/ 에 직전 모델 자동 보관 (최대 3세대)
"""
from __future__ import annotations
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT         = Path(__file__).parent.parent
ARTIFACTS    = ROOT / "models" / "artifacts"
LOG_DIR      = ROOT / "pipeline" / "logs"
DEPLOY_LOG   = ROOT / "pipeline" / "state" / "deploy_history.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "model_gate.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("model_gate")

_CROP_EN = {
    "딸기": "strawberry", "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato", "참외": "melon", "파프리카": "paprika",
}

# 배포 개선 임계값
_M2_MAPE_MIN_IMPROVEMENT = 5.0   # %p
_M1_R2_MIN_IMPROVEMENT   = 0.02


def _crop_dir(crop_ko: str) -> Path:
    return ARTIFACTS / _CROP_EN.get(crop_ko, crop_ko)


def _load_meta(meta_path: Path) -> dict:
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _m2_mape(meta: dict) -> float:
    """M2 메타에서 MAPE 추출 (키 이름 차이 대응)."""
    return float(meta.get("mape", meta.get("mape_cv", 999.0)))


def _m1_r2(meta: dict) -> float:
    """M1 메타에서 평균 R2 추출 (targets 구조 또는 test_r2_mean)."""
    if "targets" in meta:
        vals = [v.get("r2_ensemble", 0.0) for v in meta["targets"].values() if isinstance(v, dict)]
        return sum(vals) / len(vals) if vals else -1.0
    return float(meta.get("test_r2_mean", meta.get("r2", -1.0)))


def _archive_current(crop_dir: Path, generation: int = 1) -> None:
    """현재 모델을 prev/{gen}/ 에 백업. 최대 3세대 보관."""
    prev_base = crop_dir / "prev"
    # 세대 밀기: prev/2 -> prev/3, prev/1 -> prev/2, current -> prev/1
    for gen in range(3, 1, -1):
        src = prev_base / str(gen - 1)
        dst = prev_base / str(gen)
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    # 현행 → prev/1
    prev1 = prev_base / "1"
    if prev1.exists():
        shutil.rmtree(prev1)
    prev1.mkdir(parents=True, exist_ok=True)
    for f in crop_dir.iterdir():
        if f.name != "prev":
            shutil.copy2(f, prev1 / f.name)
    logger.info("  현행 모델 백업: %s", prev1)


def _deploy(candidate_dir: Path, crop_dir: Path) -> None:
    """candidate 디렉토리의 파일을 artifacts/{crop}/에 복사."""
    for f in candidate_dir.iterdir():
        dst = crop_dir / f.name
        shutil.copy2(f, dst)
        logger.info("  배포: %s", f.name)


def _log_deploy(crop: str, decision: str, old_metrics: dict, new_metrics: dict, reason: str) -> None:
    history: list = []
    if DEPLOY_LOG.exists():
        history = json.loads(DEPLOY_LOG.read_text(encoding="utf-8"))
    history.append({
        "timestamp": datetime.now().isoformat(),
        "crop": crop,
        "decision": decision,
        "reason": reason,
        "old_metrics": old_metrics,
        "new_metrics": new_metrics,
    })
    DEPLOY_LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_and_deploy(crop_ko: str, candidate_dir: Path, dry_run: bool = False) -> str:
    """신규 모델 평가 후 배포 여부 결정.

    Returns:
        "deployed" | "rejected" | "no_candidate" | "no_current"
    """
    crop_dir = _crop_dir(crop_ko)
    if not candidate_dir.exists():
        logger.warning("[%s] candidate 디렉토리 없음: %s", crop_ko, candidate_dir)
        return "no_candidate"

    # 현행 메타 로드
    current_m2 = _load_meta(crop_dir / "m2_meta.json")
    current_m1 = _load_meta(crop_dir / "m1_meta.json")

    # 신규 메타 로드
    new_m2 = _load_meta(candidate_dir / "m2_meta.json")
    new_m1 = _load_meta(candidate_dir / "m1_meta.json")

    if not new_m2 and not new_m1:
        logger.warning("[%s] candidate에 meta 파일 없음 — 배포 불가", crop_ko)
        return "no_candidate"

    # ── M2 MAPE 비교 ──────────────────────────────────────────────────────
    old_mape = _m2_mape(current_m2)
    new_mape = _m2_mape(new_m2)
    mape_improvement = old_mape - new_mape

    # ── M1 R² 비교 ────────────────────────────────────────────────────────
    old_r2 = _m1_r2(current_m1)
    new_r2 = _m1_r2(new_m1)
    r2_improvement = new_r2 - old_r2

    logger.info("[%s] M2 MAPE: %.1f%% → %.1f%% (개선: %+.1f%%p)", crop_ko, old_mape, new_mape, mape_improvement)
    logger.info("[%s] M1 R²:   %.3f → %.3f (개선: %+.3f)",     crop_ko, old_r2, new_r2, r2_improvement)

    should_deploy = (
        mape_improvement >= _M2_MAPE_MIN_IMPROVEMENT or
        r2_improvement   >= _M1_R2_MIN_IMPROVEMENT
    )

    old_metrics = {"m2_mape": old_mape, "m1_r2": old_r2}
    new_metrics = {"m2_mape": new_mape, "m1_r2": new_r2}

    if should_deploy:
        reason = []
        if mape_improvement >= _M2_MAPE_MIN_IMPROVEMENT:
            reason.append(f"M2 MAPE {mape_improvement:+.1f}%p")
        if r2_improvement >= _M1_R2_MIN_IMPROVEMENT:
            reason.append(f"M1 R² {r2_improvement:+.3f}")
        reason_str = ", ".join(reason)

        logger.info("[%s] ✅ 배포 기준 충족: %s", crop_ko, reason_str)
        if not dry_run:
            _archive_current(crop_dir)
            _deploy(candidate_dir, crop_dir)
            _log_deploy(crop_ko, "deployed", old_metrics, new_metrics, reason_str)
            logger.info("[%s] 배포 완료", crop_ko)
        else:
            logger.info("[%s] (dry_run) 실제 배포 생략", crop_ko)
        return "deployed"
    else:
        reason_str = f"M2 MAPE {mape_improvement:+.1f}%p (기준 ≥{_M2_MAPE_MIN_IMPROVEMENT}), M1 R² {r2_improvement:+.3f} (기준 ≥{_M1_R2_MIN_IMPROVEMENT})"
        logger.info("[%s] ❌ 배포 기준 미달: %s", crop_ko, reason_str)
        _log_deploy(crop_ko, "rejected", old_metrics, new_metrics, reason_str)
        return "rejected"


def rollback(crop_ko: str, generation: int = 1) -> bool:
    """prev/{generation}/으로 롤백. 성공 시 True."""
    crop_dir = _crop_dir(crop_ko)
    prev_dir = crop_dir / "prev" / str(generation)
    if not prev_dir.exists():
        logger.error("[%s] 롤백 대상 없음: %s", crop_ko, prev_dir)
        return False
    for f in prev_dir.iterdir():
        shutil.copy2(f, crop_dir / f.name)
    logger.info("[%s] 롤백 완료 (세대 %d)", crop_ko, generation)
    _log_deploy(crop_ko, f"rollback_gen{generation}", {}, {}, "manual rollback")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="모델 성능 게이트 + 자동 배포")
    parser.add_argument("--crop",     required=True, help="작물명 (한국어)")
    parser.add_argument("--candidate_dir", help="신규 모델 디렉토리 (기본: artifacts/{crop}/candidate/)")
    parser.add_argument("--dry_run",  action="store_true", help="평가만 하고 실제 배포 생략")
    parser.add_argument("--rollback", type=int, default=0, help="롤백할 세대 번호 (1=직전)")
    args = parser.parse_args()

    if args.rollback > 0:
        ok = rollback(args.crop, args.rollback)
        sys.exit(0 if ok else 1)

    candidate_dir = Path(args.candidate_dir) if args.candidate_dir else (
        _crop_dir(args.crop) / "candidate"
    )
    result = evaluate_and_deploy(args.crop, candidate_dir, dry_run=args.dry_run)
    logger.info("결과: %s", result)
    sys.exit(0 if result in ("deployed", "rejected") else 1)


if __name__ == "__main__":
    main()
