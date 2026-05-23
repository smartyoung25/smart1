"""자동 재학습 스크립트.

CLI로 직접 실행하거나 스케줄러(cron / Windows 작업 스케줄러)에서 호출.
data/collected/ 에 쌓인 신규 레코드가 임계치를 넘으면 해당 작목을 재학습합니다.

실행:
    python scripts/auto_retrain.py                   # 전체 작목 검사
    python scripts/auto_retrain.py --crop 딸기       # 단일 작목
    python scripts/auto_retrain.py --force           # 임계치 무시하고 전부 재학습
    python scripts/auto_retrain.py --mode m2         # M2만 재학습
    python scripts/auto_retrain.py --dry-run         # 실제 실행 없이 현황만 출력

환경변수:
    RETRAIN_THRESHOLD_HARVEST  (기본 10) — 수확 데이터 재학습 임계치
    RETRAIN_THRESHOLD_GROWTH   (기본 30) — 생육 데이터 재학습 임계치
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR    = ROOT / "data" / "collected"
GROWTH_DIR  = DATA_DIR / "growth"
HARVEST_DIR = DATA_DIR / "harvest"
STATE_FILE  = DATA_DIR / "retrain_state.json"

THRESHOLD_HARVEST = int(os.environ.get("RETRAIN_THRESHOLD_HARVEST", "10"))
THRESHOLD_GROWTH  = int(os.environ.get("RETRAIN_THRESHOLD_GROWTH",  "30"))


# ── 상태 파일 관리 ────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_retrain": {}, "last_count": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("[auto_retrain] 상태 저장 완료: %s", STATE_FILE)


# ── 파일 카운트 ───────────────────────────────────────────────────────────────

def count_files(directory: Path, crop_ko: str) -> int:
    if not directory.exists():
        return 0
    safe = crop_ko.replace("/", "_").replace("\\", "_")
    return len(list(directory.glob(f"{safe}_*.json")))


def count_new(directory: Path, crop_ko: str, since_count: int) -> int:
    """지난 재학습 이후 추가된 신규 레코드 수."""
    return max(0, count_files(directory, crop_ko) - since_count)


# ── 재학습 실행 ───────────────────────────────────────────────────────────────

def run_retrain(crop_ko: str, mode: str = "both", dry_run: bool = False) -> bool:
    """해당 작목의 M1/M2 재학습을 실행합니다.

    Args:
        crop_ko: 작목 한국어명
        mode: "m1" | "m2" | "both"
        dry_run: True면 실제 실행 없이 로그만 출력

    Returns:
        True if all retrains succeeded
    """
    python = sys.executable
    scripts = []
    if mode in ("m1", "both"):
        scripts.append(("M1", ROOT / "scripts" / "train_stage1_growth.py"))
    if mode in ("m2", "both"):
        scripts.append(("M2", ROOT / "scripts" / "train_stage2_yield.py"))

    success = True
    for label, script in scripts:
        cmd = [python, str(script), "--crop", crop_ko, "--no-cache-build"]
        logger.info("[auto_retrain] %s %s 재학습 시작: %s", label, crop_ko, " ".join(cmd))

        if dry_run:
            logger.info("[dry-run] 실행 생략")
            continue

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(ROOT),
            )
            if result.returncode == 0:
                logger.info("[auto_retrain] ✅ %s %s 완료", label, crop_ko)
                # stdout 마지막 5줄 출력 (R²/MAPE 결과 확인)
                lines = result.stdout.strip().splitlines()
                for ln in lines[-5:]:
                    logger.info("  %s", ln)
            else:
                logger.error(
                    "[auto_retrain] ❌ %s %s 실패 (rc=%d):\n%s",
                    label, crop_ko, result.returncode, result.stderr[-1000:],
                )
                success = False
        except subprocess.TimeoutExpired:
            logger.error("[auto_retrain] ⏰ %s %s 타임아웃 (10분 초과)", label, crop_ko)
            success = False
        except Exception as e:
            logger.error("[auto_retrain] 오류 %s %s: %s", label, crop_ko, e)
            success = False

    return success


# ── 전체 작목 순회 ───────────────────────────────────────────────────────────

def run_all(
    crop_filter: Optional[str] = None,
    mode: str = "both",
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, str]:
    """전체 작목을 순회하며 임계치 도달 작목을 재학습합니다.

    Returns:
        {crop_ko: "재학습 완료" | "임계치 미달" | "실패" | "건너뜀"}
    """
    from models.crop_config import CROP_CONFIGS

    state   = load_state()
    results = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    crops = [crop_filter] if crop_filter else list(CROP_CONFIGS.keys())

    for crop_ko in crops:
        if crop_ko not in CROP_CONFIGS:
            logger.warning("[auto_retrain] 알 수 없는 작목: %s (건너뜀)", crop_ko)
            results[crop_ko] = "알 수 없는 작목"
            continue

        g_total = count_files(GROWTH_DIR,  crop_ko)
        h_total = count_files(HARVEST_DIR, crop_ko)

        last_counts = state.get("last_count", {}).get(crop_ko, {"growth": 0, "harvest": 0})
        g_new = g_total - last_counts.get("growth",  0)
        h_new = h_total - last_counts.get("harvest", 0)

        logger.info(
            "[auto_retrain] %s — 생육 총 %d건 (+%d) / 수확 총 %d건 (+%d)",
            crop_ko, g_total, g_new, h_total, h_new,
        )

        # 재학습 여부 결정
        should_train = force
        train_mode   = mode
        reason        = ""

        if not should_train:
            if h_new >= THRESHOLD_HARVEST:
                should_train = True
                train_mode   = "both"
                reason = f"수확 신규 {h_new}건 ≥ {THRESHOLD_HARVEST}"
            elif g_new >= THRESHOLD_GROWTH:
                should_train = True
                train_mode   = "m1"
                reason = f"생육 신규 {g_new}건 ≥ {THRESHOLD_GROWTH}"

        if not should_train:
            msg = (f"임계치 미달 (생육 신규 {g_new}/{THRESHOLD_GROWTH} / "
                   f"수확 신규 {h_new}/{THRESHOLD_HARVEST})")
            logger.info("[auto_retrain] ⏭  %s: %s", crop_ko, msg)
            results[crop_ko] = msg
            continue

        logger.info("[auto_retrain] 🔄 %s 재학습 시작 (%s) — 이유: %s",
                    crop_ko, train_mode, reason or "강제실행")

        ok = run_retrain(crop_ko, mode=train_mode, dry_run=dry_run)

        if ok:
            results[crop_ko] = f"재학습 완료 ({train_mode})"
            # 상태 갱신
            if not dry_run:
                state.setdefault("last_retrain", {})[crop_ko] = now_iso
                state.setdefault("last_count",   {})[crop_ko] = {
                    "growth":  g_total,
                    "harvest": h_total,
                }
        else:
            results[crop_ko] = "재학습 실패"

    if not dry_run:
        save_state(state)

    return results


# ── 결과 리포트 ───────────────────────────────────────────────────────────────

def print_report(results: dict[str, str]) -> None:
    print("\n" + "="*55)
    print("  자동 재학습 결과 리포트")
    print("="*55)
    for crop, status in results.items():
        icon = "✅" if "완료" in status else ("❌" if "실패" in status else "⏭ ")
        print(f"  {icon} {crop:<12} {status}")
    print("="*55 + "\n")


# ── CLI 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="스마트팜 모델 자동 재학습")
    parser.add_argument("--crop",    type=str, default=None,
                        help="특정 작목만 재학습 (예: 딸기)")
    parser.add_argument("--mode",    type=str, default="both",
                        choices=["m1", "m2", "both"],
                        help="재학습 모드 (기본: both)")
    parser.add_argument("--force",   action="store_true",
                        help="임계치 무시하고 즉시 재학습")
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 실행 없이 현황만 출력")
    args = parser.parse_args()

    logger.info("=== 스마트팜 자동 재학습 시작 ===")
    logger.info("임계치: 수확 %d건 / 생육 %d건", THRESHOLD_HARVEST, THRESHOLD_GROWTH)

    results = run_all(
        crop_filter=args.crop,
        mode=args.mode,
        force=args.force,
        dry_run=args.dry_run,
    )
    print_report(results)

    # 실패 작목이 있으면 exit code 1
    if any("실패" in v for v in results.values()):
        sys.exit(1)
