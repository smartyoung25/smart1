"""Priva P/I 배액 교정 컨트롤러 상태 영속화.

농장별로 PIControllerState.i_action_lm2 값을 일간 JSON에 저장해
다음날 관수 스케줄 계산 시 연속 적분 항(I-term)이 유지되도록 합니다.

저장 경로: api/data/priva_pi/{farm_id}.json
형식:
{
    "farm_id": "farm_001",
    "updated_at": "2026-05-22",
    "i_action_lm2": 0.023,
    "drain_actual_pct_last": 18.5,
    "drain_target_pct": 20.0
}
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT    = Path(__file__).resolve().parents[2]
_PI_DIR  = _ROOT / "api" / "data" / "priva_pi"
_lock    = Lock()


def _pi_path(farm_id: str) -> Path:
    _PI_DIR.mkdir(parents=True, exist_ok=True)
    return _PI_DIR / f"{farm_id}.json"


def load_pi_state(farm_id: str) -> dict:
    """저장된 PI 상태를 로드한다.

    Returns:
        {"i_action_lm2": float, "drain_actual_pct_last": float | None,
         "drain_target_pct": float, "updated_at": str}
        파일 없으면 기본값 반환.
    """
    path = _pi_path(farm_id)
    try:
        with _lock:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return {
                    "i_action_lm2":         float(data.get("i_action_lm2", 0.0)),
                    "drain_actual_pct_last": data.get("drain_actual_pct_last"),
                    "drain_target_pct":      float(data.get("drain_target_pct", 20.0)),
                    "updated_at":            data.get("updated_at", ""),
                }
    except Exception as e:
        logger.warning("[priva_pi_store] load 실패 farm=%s: %s", farm_id, e)
    return {"i_action_lm2": 0.0, "drain_actual_pct_last": None,
            "drain_target_pct": 20.0, "updated_at": ""}


def save_pi_state(
    farm_id: str,
    i_action_lm2: float,
    drain_actual_pct: Optional[float] = None,
    drain_target_pct: float = 20.0,
) -> None:
    """PI 상태를 저장한다."""
    path = _pi_path(farm_id)
    data = {
        "farm_id":               farm_id,
        "updated_at":            str(date.today()),
        "i_action_lm2":          round(float(i_action_lm2), 6),
        "drain_actual_pct_last": drain_actual_pct,
        "drain_target_pct":      float(drain_target_pct),
    }
    try:
        with _lock:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("[priva_pi_store] saved farm=%s i=%.4f", farm_id, i_action_lm2)
    except Exception as e:
        logger.warning("[priva_pi_store] save 실패 farm=%s: %s", farm_id, e)


def reset_pi_state(farm_id: str) -> None:
    """특정 농장의 PI 상태를 초기화한다."""
    path = _pi_path(farm_id)
    try:
        with _lock:
            if path.exists():
                path.unlink()
        logger.info("[priva_pi_store] reset farm=%s", farm_id)
    except Exception as e:
        logger.warning("[priva_pi_store] reset 실패 farm=%s: %s", farm_id, e)


def get_last_drain_actual(farm_id: str) -> Optional[float]:
    """마지막으로 저장된 실측 배액률을 반환한다.

    irrigation_store에서 읽지 못할 때 fallback으로 사용.
    """
    state = load_pi_state(farm_id)
    return state.get("drain_actual_pct_last")
