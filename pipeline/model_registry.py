"""모델 버전 레지스트리 — 경량 JSON 기반, 외부 MLflow 의존성 없음.

설계 원칙:
  - 학습 스크립트는 기존대로 models/artifacts/{crop_en}/ 에 직접 저장
  - 재학습 *전*: 현재 아티팩트를 models/artifacts/.versions/{crop_en}/v{N}/ 에 스냅샷
  - 재학습 *후*: 새 아티팩트를 레지스트리에 등록 (v{N+1})
  - 게이트 실패 시: v{N}/ 에서 canonical 경로로 복원 (롤백)
  - model_loader.py는 수정 없이 기존 canonical 경로를 그대로 사용

레지스트리 파일: models/registry.json
버전 아티팩트:  models/artifacts/.versions/{crop_en}/v{N}/
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:                                    # 게이트 단일 출처 (pipeline/gates.py)
    from pipeline.gates import evaluate_m2_gate
except ImportError:                     # 스크립트 직접 실행 등 경로 미설정 시
    from gates import evaluate_m2_gate

logger = logging.getLogger(__name__)

ROOT          = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / "models" / "artifacts"
REGISTRY_FILE = ROOT / "models" / "registry.json"

# ── 작목 영문명 매핑 (model_loader와 동기화) ──────────────────────────────────
CROP_EN: dict[str, str] = {
    "딸기":       "strawberry",
    "방울토마토": "cherry_tomato",
    "완숙토마토": "tomato",
    "참외":       "melon",
    "파프리카":   "paprika",
    "오이":       "cucumber",
}
CROP_KO: dict[str, str] = {v: k for k, v in CROP_EN.items()}


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("[registry] registry.json 읽기 실패: %s", e)
    return {}


def _save_registry(data: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _crop_artifact_dir(crop_en: str) -> Path:
    """canonical 아티팩트 디렉터리 (model_loader가 읽는 경로)."""
    return ARTIFACTS_DIR / crop_en


def _version_dir(crop_en: str, version: int) -> Path:
    """버전별 스냅샷 디렉터리 (canonical 경로 밖 .versions/ 에 저장)."""
    return ARTIFACTS_DIR / ".versions" / crop_en / f"v{version}"


def _read_pipeline_meta(crop_en: str) -> dict:
    """canonical 경로의 pipeline_meta.json 읽기."""
    meta_path = _crop_artifact_dir(crop_en) / "pipeline_meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── Public API ────────────────────────────────────────────────────────────────

def snapshot_before_retrain(crop_en: str) -> Optional[int]:
    """재학습 *전* 현재 아티팩트를 .versions/ 아래 버전 디렉터리에 백업.

    Returns:
        백업된 버전 번호 (없으면 None)
    """
    canon = _crop_artifact_dir(crop_en)
    if not canon.exists():
        logger.info("[registry] %s 아티팩트 없음 — 스냅샷 건너뜀", crop_en)
        return None

    # .versions/{crop_en}/ 에서 기존 스냅샷 번호를 스캔해 다음 버전 결정
    versions_base = ARTIFACTS_DIR / ".versions" / crop_en
    if versions_base.exists():
        existing = sorted(
            int(d.name[1:]) for d in versions_base.iterdir()
            if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()
        )
    else:
        existing = []
    next_snap = (existing[-1] if existing else 0) + 1

    snap_dir = _version_dir(crop_en, next_snap)
    try:
        # canonical 경로를 .versions/ 아래에 복사 (canon 내부에 중첩되지 않음)
        shutil.copytree(canon, snap_dir, dirs_exist_ok=False)
        logger.info("[registry] %s 스냅샷 → v%d (%s)", crop_en, next_snap, snap_dir)
        return next_snap
    except Exception as e:
        logger.error("[registry] 스냅샷 실패 %s: %s", crop_en, e)
        return None


def register_version(
    crop_en: str,
    mape_stage2: Optional[float] = None,
    mape_stage3: Optional[float] = None,
    cv_r2: Optional[float] = None,
    gate_passed: bool = True,
    triggered_by: str = "retrain",
    snapshot_version: Optional[int] = None,
) -> int:
    """재학습 완료 후 새 버전을 레지스트리에 등록.

    pipeline_meta.json에서 MAPE/R² 자동 추출 (인자로 오버라이드 가능).

    Returns:
        등록된 버전 번호
    """
    meta = _read_pipeline_meta(crop_en)
    s2_meta = meta.get("stage2", {})
    s3_meta = meta.get("stage3", {})

    mape_stage2 = mape_stage2 if mape_stage2 is not None else s2_meta.get("mape")
    mape_stage3 = mape_stage3 if mape_stage3 is not None else s3_meta.get("mape")
    cv_r2       = cv_r2       if cv_r2       is not None else s2_meta.get("cv_r2_mean")

    # ★ 게이트는 pipeline/gates.py 단일 정책으로 판정 (구: s2_meta.gate_passed 맹신 →
    #   완화기준으로 MAPE 60%대 모델까지 활성화되던 문제). 호출자가 gate_passed=False를
    #   명시하면(재학습 실패 등) 그대로 폴백 유지.
    _n_train  = s2_meta.get("n_train") or s2_meta.get("n_season") or s2_meta.get("n_samples")
    _verdict  = evaluate_m2_gate(mape_stage2, cv_r2, _n_train, s2_meta.get("train_r2"))
    gate_passed = gate_passed and _verdict["serve_m2"]
    logger.info("[registry] %s 게이트 판정=%s (%s)", crop_en, _verdict["label"],
                "; ".join(_verdict["reasons"] + _verdict["flags"]))

    reg = _load_registry()
    crop_entry = reg.setdefault(crop_en, {"active_version": None, "versions": []})
    versions   = crop_entry["versions"]

    new_version = (versions[-1]["version"] if versions else 0) + 1

    entry = {
        "version":          new_version,
        "timestamp":        datetime.now(tz=timezone.utc).isoformat(),
        "triggered_by":     triggered_by,
        "mape_stage2":      round(mape_stage2, 4) if mape_stage2 is not None else None,
        "mape_stage3":      round(mape_stage3, 4) if mape_stage3 is not None else None,
        "cv_r2":            round(cv_r2, 4)        if cv_r2       is not None else None,
        "n_train":          _n_train,
        "verdict":          _verdict["verdict"],       # serve | conditional | fallback
        "gate_flags":       _verdict["flags"],
        "gate_passed":      gate_passed,
        "is_active":        gate_passed,
        "snapshot_version": snapshot_version,
    }
    versions.append(entry)

    if gate_passed:
        for v in versions[:-1]:
            v["is_active"] = False
        crop_entry["active_version"] = new_version
        logger.info("[registry] %s v%d 등록·활성화 (MAPE=%.2f%%)",
                    crop_en, new_version, mape_stage2 or 0)
    else:
        logger.warning("[registry] %s v%d 등록 (게이트 실패 — 비활성)", crop_en, new_version)

    _save_registry(reg)
    return new_version


def rollback(crop_en: str, target_version: Optional[int] = None) -> bool:
    """지정 버전(기본: 직전 활성 버전)으로 롤백.

    canonical 경로에 해당 버전 아티팩트를 덮어씁니다.

    Returns:
        True if rollback succeeded
    """
    reg = _load_registry()
    crop_entry = reg.get(crop_en, {})
    versions   = crop_entry.get("versions", [])

    if not versions:
        logger.error("[registry] %s 버전 이력 없음", crop_en)
        return False

    if target_version is None:
        active = crop_entry.get("active_version")
        active_entry = next((v for v in versions if v["version"] == active), None)
        if active_entry and active_entry.get("snapshot_version"):
            target_version = active_entry["snapshot_version"]
        else:
            active_idx = next(
                (i for i, v in enumerate(versions) if v["version"] == active), -1
            )
            if active_idx > 0:
                target_version = versions[active_idx - 1]["version"]

    if target_version is None:
        logger.error("[registry] %s 롤백 대상 버전을 찾을 수 없음", crop_en)
        return False

    snap_dir = _version_dir(crop_en, target_version)
    if not snap_dir.exists():
        logger.error("[registry] 스냅샷 디렉터리 없음: %s", snap_dir)
        return False

    canon = _crop_artifact_dir(crop_en)
    try:
        for item in snap_dir.iterdir():
            dest = canon / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)

        for v in versions:
            v["is_active"] = v["version"] == target_version
        crop_entry["active_version"] = target_version
        _save_registry(reg)

        logger.info("[registry] %s 롤백 완료 → v%d", crop_en, target_version)
        return True
    except Exception as e:
        logger.error("[registry] 롤백 실패 %s → v%d: %s", crop_en, target_version, e)
        return False


def get_versions(crop_en: str) -> list[dict]:
    """작목의 모든 버전 이력 반환 (최신순)."""
    reg = _load_registry()
    crop_entry = reg.get(crop_en, {})
    return list(reversed(crop_entry.get("versions", [])))


def get_active_version(crop_en: str) -> Optional[dict]:
    """현재 활성 버전 메타데이터 반환."""
    reg = _load_registry()
    crop_entry = reg.get(crop_en, {})
    active_num = crop_entry.get("active_version")
    if active_num is None:
        return None
    versions = crop_entry.get("versions", [])
    return next((v for v in versions if v["version"] == active_num), None)


def get_all_active_versions() -> dict[str, Optional[dict]]:
    """모든 작목의 현재 활성 버전 요약 반환."""
    reg = _load_registry()
    result = {}
    for crop_en in CROP_EN.values():
        crop_entry = reg.get(crop_en, {})
        active_num = crop_entry.get("active_version")
        versions   = crop_entry.get("versions", [])
        active_v   = next((v for v in versions if v["version"] == active_num), None)
        result[crop_en] = active_v
    return result


def compare_versions(crop_en: str, version_a: int, version_b: int) -> dict:
    """두 버전의 지표 비교."""
    reg = _load_registry()
    versions = reg.get(crop_en, {}).get("versions", [])
    va = next((v for v in versions if v["version"] == version_a), None)
    vb = next((v for v in versions if v["version"] == version_b), None)

    if not va or not vb:
        return {"error": f"버전 {version_a} 또는 {version_b}를 찾을 수 없습니다."}

    def _delta(key):
        a, b = va.get(key), vb.get(key)
        if a is not None and b is not None:
            return round(b - a, 4)
        return None

    return {
        "crop_en":   crop_en,
        "version_a": va,
        "version_b": vb,
        "delta": {
            "mape_stage2": _delta("mape_stage2"),
            "mape_stage3": _delta("mape_stage3"),
            "cv_r2":       _delta("cv_r2"),
        },
    }


def cleanup_old_snapshots(crop_en: str, keep_n: int = 5) -> int:
    """오래된 스냅샷 디렉터리 정리 (최근 N개 유지).

    Returns:
        삭제된 스냅샷 수
    """
    reg = _load_registry()
    crop_entry = reg.get(crop_en, {})
    active_num = crop_entry.get("active_version")
    versions   = crop_entry.get("versions", [])

    if len(versions) <= keep_n:
        return 0

    keep_versions = {v["version"] for v in versions[-keep_n:]}
    if active_num:
        keep_versions.add(active_num)

    removed = 0
    for v in versions:
        ver_num = v["version"]
        if ver_num not in keep_versions:
            snap_dir = _version_dir(crop_en, ver_num)
            if snap_dir.exists():
                try:
                    shutil.rmtree(snap_dir)
                    removed += 1
                    logger.info("[registry] 스냅샷 삭제: %s v%d", crop_en, ver_num)
                except Exception as e:
                    logger.warning(
                        "[registry] 스냅샷 삭제 실패 %s v%d: %s", crop_en, ver_num, e
                    )
    return removed
