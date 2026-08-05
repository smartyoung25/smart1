"""자동 재학습 트리거

pipeline/state/new_rows_since_retrain.json을 읽어 누적 신규 행이
임계값을 초과하면 M1/M2 재학습을 실행한다.

사용:
    python retrain_trigger.py [--threshold 500] [--crops 딸기 완숙토마토] [--force]

임계값 기본값:
    env 신규 행 500개 이상 OR prod 신규 행 200개 이상
"""
from __future__ import annotations
import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT      = Path(__file__).parent.parent
STATE_DIR = ROOT / "pipeline" / "state"
LOG_DIR   = ROOT / "pipeline" / "logs"

STATE_FILE   = STATE_DIR / "new_rows_since_retrain.json"
RETRAIN_LOG  = STATE_DIR / "retrain_history.json"
LOCK_FILE    = STATE_DIR / "retrain_trigger.lock"

# 학습 스크립트는 pipeline/train/ 아래에 위치 (Docker 컨테이너 내에서도 동일 경로)
TRAIN_DIR       = ROOT / "pipeline" / "train"
TRAIN_M1_SCRIPT = TRAIN_DIR / "train_m1.py"
TRAIN_M2_SCRIPT = TRAIN_DIR / "train_m2.py"    # v4 Optuna-tuned
PREP_M1_SCRIPT  = TRAIN_DIR / "prep_m1.py"

ALL_CROPS = ["딸기", "방울토마토", "완숙토마토", "참외", "파프리카", "오이"]  # ★ 오이 추가 — 서빙작목인데 자동재학습 대상서 누락됐었음

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "retrain_trigger.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("retrain_trigger")


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"new_env_rows": 0, "new_prod_rows": 0, "last_updated": None}


def _reset_state() -> None:
    state = {"new_env_rows": 0, "new_prod_rows": 0, "last_updated": datetime.now().isoformat()}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _log_retrain(crops: list[str], triggered_by: str, results: dict) -> None:
    history: list = []
    if RETRAIN_LOG.exists():
        history = json.loads(RETRAIN_LOG.read_text(encoding="utf-8"))
    history.append({
        "timestamp": datetime.now().isoformat(),
        "triggered_by": triggered_by,
        "crops": crops,
        "results": results,
    })
    RETRAIN_LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_script(script: Path, crop: str, extra_args: list[str] | None = None) -> dict:
    """Python 스크립트를 subprocess로 실행하고 결과 반환."""
    if not script.exists():
        logger.warning("스크립트 없음: %s -- 건너뜀", script)
        return {"status": "skipped", "reason": "script not found"}

    cmd = [sys.executable, str(script), crop] + (extra_args or [])
    logger.info("  실행: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600, cwd=str(script.parent)
        )
        status = "ok" if result.returncode == 0 else "failed"
        if result.returncode != 0:
            logger.error("  [%s] 실패 (rc=%d)\n%s", script.name, result.returncode, result.stderr[-500:])
        else:
            logger.info("  [%s] 완료", script.name)
        return {"status": status, "returncode": result.returncode, "stderr_tail": result.stderr[-200:]}
    except subprocess.TimeoutExpired:
        logger.error("  [%s] 타임아웃 (600s)", script.name)
        return {"status": "timeout"}
    except Exception as e:
        logger.error("  [%s] 예외: %s", script.name, e)
        return {"status": "error", "error": str(e)}


def retrain_crop(crop: str) -> dict:
    """단일 작물 M1+M2 재학습 실행 (버전 레지스트리 통합)."""
    import time
    from pipeline.notifier import notify_retrain
    from pipeline.model_registry import (
        CROP_EN, snapshot_before_retrain, register_version, rollback,
        cleanup_old_snapshots,
    )

    logger.info("=== %s 재학습 시작 ===", crop)
    t0 = time.monotonic()
    results = {}

    crop_en = CROP_EN.get(crop)

    # ── 재학습 전 현재 아티팩트 스냅샷 ──────────────────────────────────────────
    snap_version = None
    if crop_en:
        snap_version = snapshot_before_retrain(crop_en)
        if snap_version:
            logger.info("  [registry] %s 스냅샷 v%d 생성", crop, snap_version)

    # Step 1: M1 피처 엔지니어링
    results["prep_m1"] = _run_script(PREP_M1_SCRIPT, crop)

    # Step 2: M1 학습
    if results["prep_m1"]["status"] in ("ok", "skipped"):
        results["train_m1"] = _run_script(TRAIN_M1_SCRIPT, crop)
    else:
        results["train_m1"] = {"status": "skipped", "reason": "prep_m1 failed"}

    # Step 3: M2 학습 (env+prod 조인 → 시즌 집계는 train_m2 내부에서 수행)
    results["train_m2"] = _run_script(TRAIN_M2_SCRIPT, crop)

    # Step 4: 모델 게이트 — candidate/ → canonical/ 승격 (MAPE 개선 시만)
    _gate_result = "skipped"
    if results["train_m2"]["status"] == "ok" and crop_en:
        try:
            from pipeline.model_gate import evaluate_and_deploy
            cand_dir = ROOT / "models" / "artifacts" / crop_en / "candidate"
            _gate_result = evaluate_and_deploy(crop, candidate_dir=cand_dir)
            results["model_gate"] = _gate_result
            logger.info("  [gate] %s model_gate → %s", crop, _gate_result)
        except Exception as _mge:
            logger.warning("  [gate] model_gate 실행 실패(무시): %s", _mge)
            results["model_gate"] = f"error: {_mge}"

    ok_count = sum(1 for v in results.values() if v["status"] == "ok")
    duration = time.monotonic() - t0
    # M2 학습 성공이 핵심 게이트 (prep/M1 실패는 경고만)
    success  = results["train_m2"]["status"] == "ok"
    logger.info("=== %s 재학습 완료: %d/3 성공 (gate=%s) ===", crop, ok_count, _gate_result)

    # ── 버전 레지스트리 등록 ──────────────────────────────────────────────────────
    # candidate/m2_meta.json에서 실제 MAPE를 읽어 게이트 판정
    # (train_m2.py는 pipeline_meta.json이 아닌 candidate/m2_meta.json에 저장하므로 직접 읽음)
    _cand_mape: float | None = None
    _cand_r2:   float | None = None
    if crop_en and success:
        try:
            import json as _j
            _cand_path = ROOT / "models" / "artifacts" / crop_en / "candidate" / "m2_meta.json"
            if _cand_path.exists():
                _cm = _j.loads(_cand_path.read_text(encoding="utf-8"))
                _cand_mape = float(_cm.get("mape", 999.0))
                _cand_r2   = float(_cm.get("cv_r2_mean", _cm.get("train_r2", -1.0)))
                logger.info("  [gate] %s candidate MAPE=%.1f%% cv_R²=%.3f", crop, _cand_mape, _cand_r2)
        except Exception as _ge:
            logger.warning("  [gate] candidate 메타 읽기 실패: %s", _ge)

    # model_gate가 "deployed"를 반환해야만 registry 활성화
    # (canonical 파일이 실제로 갱신된 경우에만 새 버전을 active로 등록)
    _gate = _gate_result == "deployed"

    if crop_en:
        if success:
            new_ver = register_version(
                crop_en=crop_en,
                mape_stage2=_cand_mape,
                cv_r2=_cand_r2,
                gate_passed=_gate,
                triggered_by="retrain_trigger",
                snapshot_version=snap_version,
            )
            results["registry_version"] = new_ver
            if _gate:
                logger.info("  [registry] %s 신규 버전 v%d 등록·활성화 (MAPE=%.1f%%)",
                            crop, new_ver, _cand_mape or 0)
            else:
                logger.info("  [registry] %s 신규 버전 v%d 등록 (게이트 미달, 비활성)", crop, new_ver)

            # canonical 갱신된 경우에만 API 서버의 모델 캐시 무효화
            if _gate:
                try:
                    from api.services.model_loader import clear_model_cache
                    cleared = clear_model_cache()
                    logger.info("  [cache] 모델 캐시 초기화: %s", cleared)
                except Exception as _ce:
                    logger.warning("  [cache] 캐시 초기화 실패(무시): %s", _ce)

            # 오래된 스냅샷 정리 (최근 5개 유지)
            removed = cleanup_old_snapshots(crop_en, keep_n=5)
            if removed:
                logger.info("  [registry] 오래된 스냅샷 %d개 정리", removed)
        else:
            # 재학습 실패 → 스냅샷에서 자동 롤백
            register_version(
                crop_en=crop_en,
                gate_passed=False,
                triggered_by="retrain_trigger",
                snapshot_version=snap_version,
            )
            if snap_version:
                logger.warning("  [registry] %s 재학습 실패(MAPE=%.1f%%) — v%d로 자동 롤백",
                               crop, _cand_mape or 999, snap_version)
                rb_ok = rollback(crop_en, target_version=snap_version)
                results["rollback"] = "ok" if rb_ok else "failed"
            else:
                logger.warning("  [registry] %s 재학습 실패 — 스냅샷 없어 롤백 불가", crop)

    # ── 알림 발송 ─────────────────────────────────────────────────────────────
    err_msg = None
    if not success:
        failed = [k for k, v in results.items()
                  if isinstance(v, dict) and v.get("status") not in ("ok", "skipped")]
        err_msg = "; ".join(
            f"{k}: {results[k].get('stderr_tail','')[:150]}" for k in failed
            if isinstance(results[k], dict)
        )
    try:
        notify_retrain(
            crop=crop, success=success,
            duration_s=duration, error_msg=err_msg,
        )
    except Exception as e:
        logger.warning("[notifier] 알림 발송 오류 (무시): %s", e)

    return results


def should_trigger(state: dict, env_threshold: int, prod_threshold: int, force: bool) -> tuple[bool, str]:
    if force:
        return True, "force"
    if state["new_env_rows"] >= env_threshold:
        return True, f"env_rows={state['new_env_rows']} >= {env_threshold}"
    if state["new_prod_rows"] >= prod_threshold:
        return True, f"prod_rows={state['new_prod_rows']} >= {prod_threshold}"
    return False, f"env={state['new_env_rows']}/{env_threshold}, prod={state['new_prod_rows']}/{prod_threshold}"


def run(args: argparse.Namespace) -> None:
    from pipeline.notifier import notify_threshold

    # 동시 실행 방지: 락 파일 획득 (이미 실행 중이면 즉시 종료)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # ★ stale 락 회수 — SIGKILL/재부팅으로 남은 락이 이후 재학습을 영구 차단하던 문제(TTL 2h)
    import time as _t
    try:
        if LOCK_FILE.exists() and (_t.time() - LOCK_FILE.stat().st_mtime) > 7200:
            LOCK_FILE.unlink()
            logger.warning("[retrain_trigger] stale 락(>2h) 회수: %s", LOCK_FILE)
    except Exception:
        pass
    try:
        lock_fd = LOCK_FILE.open("x")   # exclusive create — 이미 존재하면 FileExistsError
    except FileExistsError:
        logger.warning("[retrain_trigger] 이미 재학습이 실행 중 — 중복 실행 방지로 종료 (lock: %s)", LOCK_FILE)
        return

    try:
        state = _load_state()
        trigger, reason = should_trigger(state, args.env_threshold, args.prod_threshold, args.force)

        if not trigger:
            logger.info("재학습 불필요: %s", reason)
            return

        logger.info("재학습 트리거 발동: %s", reason)

        # 재학습 시작 전 임계값 초과 알림 (force 제외)
        if reason != "force":
            try:
                notify_threshold(
                    env_rows=state["new_env_rows"],
                    prod_rows=state["new_prod_rows"],
                    env_threshold=args.env_threshold,
                    prod_threshold=args.prod_threshold,
                )
            except Exception as e:
                logger.warning("[notifier] 임계값 알림 오류 (무시): %s", e)

        crops = args.crops or ALL_CROPS
        all_results = {}

        for crop in crops:
            all_results[crop] = retrain_crop(crop)

        _log_retrain(crops, reason, all_results)
        _reset_state()
        logger.info("[완료] 재학습 이력 저장: %s", RETRAIN_LOG)
    finally:
        lock_fd.close()
        LOCK_FILE.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="스마트팜 자동 재학습 트리거")
    parser.add_argument("--env_threshold",  type=int, default=500,
                        help="환경 신규 행 임계값 (기본 500)")
    parser.add_argument("--prod_threshold", type=int, default=200,
                        help="생산량 신규 행 임계값 (기본 200)")
    parser.add_argument("--crops", nargs="+",
                        help="재학습 작물 목록 (기본: 전체 5작목)")
    parser.add_argument("--force", action="store_true",
                        help="임계값 무관하게 즉시 재학습")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
