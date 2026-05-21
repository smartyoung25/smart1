"""Smart Farm — 작물별 최적 재배 환경 이탈 감지 + 권고 알림

작동 방식:
    MQTT 구독자(mqtt_subscriber.py)가 환경 메시지를 수신할 때 이 모듈의
    check_and_notify()를 호출합니다.
    각 농장·항목별로 최적 범위를 벗어나면 이메일/SMS/카카오 알림톡으로
    재배 조정 권고를 발송합니다.

    ※ 단순 센서 이상값(SENSOR_RANGE 초과)은 mqtt_subscriber가 직접 처리.
       이 모듈은 센서가 정상 범위 내에 있더라도 작물 생육에 불리한 구간을
       감지해 "권고" 수준으로 알립니다.

쿨다운:
    동일 농장·동일 항목에 대해 COOLDOWN_SEC(기본 30분) 이내 중복 발송 방지.

환경변수:
    ADVISOR_COOLDOWN_SEC   : 농장별 쿨다운 초 (기본: 1800 = 30분)
    ADVISOR_DRY_RUN        : "1"이면 알림 미발송, 콘솔 출력만
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

COOLDOWN_SEC    = int(os.environ.get("ADVISOR_COOLDOWN_SEC", "1800"))
DRY_RUN         = os.environ.get("ADVISOR_DRY_RUN", "0") == "1"
_MAX_HISTORY    = 500   # advisor_history.json 최대 보관 건수

ROOT            = Path(__file__).parent.parent
_HISTORY_PATH   = ROOT / "pipeline" / "state" / "advisor_history.json"
_history_lock   = threading.Lock()

# ── 쿨다운 추적 (farm_id + field → 마지막 발송 시각) ──────────────────────────
_last_notified: dict[str, float] = {}


# ── 작물별 최적 재배 환경 범위 및 권고 조치 ──────────────────────────────────
# 구조: {crop_ko: {field: {"optimal": (lo, hi), "high_action": str, "low_action": str}}}
#
# 참고 자료:
#   - 농촌진흥청 작물별 재배기술서
#   - 국립원예특작과학원 스마트팜 모델 하우스 기준

CROP_OPTIMAL: dict[str, dict[str, dict]] = {
    "딸기": {
        "temp_internal": {
            "optimal":     (18.0, 25.0),
            "high_action": "환기팬 가동 또는 차광막을 점검하세요. 고온은 기형과·착색 불량을 유발합니다.",
            "low_action":  "난방기를 점검하고 보온 커튼을 닫아 최저 온도 18°C를 유지하세요.",
        },
        "humidity_int": {
            "optimal":     (60.0, 80.0),
            "high_action": "환기를 강화해 흰가루병·잿빛곰팡이병 발생을 예방하세요.",
            "low_action":  "미스트 또는 관수량을 늘려 습도를 높이세요.",
        },
        "co2_ppm": {
            "optimal":     (600.0, 1200.0),
            "high_action": "환기창을 열어 CO₂를 낮추세요.",
            "low_action":  "CO₂ 발생기 가동 시간을 늘려 광합성을 촉진하세요.",
        },
        "soil_temp": {
            "optimal":     (12.0, 18.0),
            "high_action": "관수 시 차가운 물을 사용하거나 멀칭을 점검하세요.",
            "low_action":  "지중 난방 또는 흑색 필름 멀칭으로 지온을 높이세요.",
        },
        "ec_dsm": {
            "optimal":     (1.0, 2.5),
            "high_action": "양액 EC가 높습니다. 청수 비율을 높여 희석하세요.",
            "low_action":  "양액 농도가 낮습니다. 원액 공급량을 늘리세요.",
        },
    },
    "방울토마토": {
        "temp_internal": {
            "optimal":     (20.0, 28.0),
            "high_action": "차광·환기로 온도를 낮추세요. 30°C 초과 시 화분 불량이 발생합니다.",
            "low_action":  "야간 보온 강화 — 최저 15°C 이상 유지가 필요합니다.",
        },
        "humidity_int": {
            "optimal":     (55.0, 75.0),
            "high_action": "환기를 늘려 잿빛곰팡이 및 역병 예방하세요.",
            "low_action":  "관수·미스트로 습도를 보충하세요.",
        },
        "co2_ppm": {
            "optimal":     (800.0, 1500.0),
            "high_action": "환기를 강화하세요.",
            "low_action":  "CO₂ 농도 강화로 과실 비대를 촉진하세요.",
        },
        "soil_temp": {
            "optimal":     (15.0, 22.0),
            "high_action": "지온 과열 — 관수량 조정 또는 멀칭 점검하세요.",
            "low_action":  "지온 저하 — 지중 난방 점검하세요.",
        },
        "ec_dsm": {
            "optimal":     (2.0, 3.5),
            "high_action": "EC 과다 — 청수 관수 비율을 높이세요.",
            "low_action":  "EC 부족 — 양액 농도를 높이세요.",
        },
    },
    "완숙토마토": {
        "temp_internal": {
            "optimal":     (18.0, 27.0),
            "high_action": "고온 장애 주의. 환기·차광으로 온도를 낮추세요.",
            "low_action":  "야간 저온 주의. 보온 강화가 필요합니다.",
        },
        "humidity_int": {
            "optimal":     (50.0, 75.0),
            "high_action": "환기 강화로 과습을 예방하세요.",
            "low_action":  "관수 또는 미스트로 습도를 올리세요.",
        },
        "co2_ppm": {
            "optimal":     (800.0, 1500.0),
            "high_action": "환기로 CO₂를 낮추세요.",
            "low_action":  "CO₂ 시비로 광합성 효율을 높이세요.",
        },
        "soil_temp": {
            "optimal":     (16.0, 22.0),
            "high_action": "지온 과열 — 멀칭·관수 조정하세요.",
            "low_action":  "지온 저하 — 지중 난방 점검하세요.",
        },
        "ec_dsm": {
            "optimal":     (2.0, 3.5),
            "high_action": "EC 과다 — 희석하세요.",
            "low_action":  "EC 부족 — 양액 농도를 높이세요.",
        },
    },
    "참외": {
        "temp_internal": {
            "optimal":     (22.0, 30.0),
            "high_action": "차광·환기로 온도를 낮추세요. 과실 착색에 영향을 줍니다.",
            "low_action":  "보온 강화 — 최저 야간 온도 18°C 이상 유지하세요.",
        },
        "humidity_int": {
            "optimal":     (55.0, 75.0),
            "high_action": "과습 시 흰가루병 발생 위험이 높습니다. 환기하세요.",
            "low_action":  "건조 시 관수를 늘리세요.",
        },
        "co2_ppm": {
            "optimal":     (600.0, 1200.0),
            "high_action": "환기를 강화하세요.",
            "low_action":  "CO₂ 시비로 과실 비대를 촉진하세요.",
        },
        "soil_temp": {
            "optimal":     (18.0, 26.0),
            "high_action": "지온 과열 — 관수량 조정하세요.",
            "low_action":  "지온 저하 — 지중 난방을 가동하세요.",
        },
        "ec_dsm": {
            "optimal":     (1.5, 3.0),
            "high_action": "EC 과다 — 희석 관수하세요.",
            "low_action":  "EC 부족 — 양액 농도를 높이세요.",
        },
    },
    "파프리카": {
        "temp_internal": {
            "optimal":     (20.0, 28.0),
            "high_action": "환기·차광으로 고온 장애를 예방하세요. 30°C 이상 시 착과 불량 발생합니다.",
            "low_action":  "야간 보온 강화 — 최저 15°C 이상 유지하세요.",
        },
        "humidity_int": {
            "optimal":     (60.0, 80.0),
            "high_action": "환기로 과습을 해소하세요.",
            "low_action":  "미스트 또는 관수로 습도를 높이세요.",
        },
        "co2_ppm": {
            "optimal":     (800.0, 1500.0),
            "high_action": "환기창을 열어 CO₂를 낮추세요.",
            "low_action":  "CO₂ 발생기를 가동해 광합성을 촉진하세요.",
        },
        "soil_temp": {
            "optimal":     (18.0, 24.0),
            "high_action": "지온 과열 — 멀칭 점검 또는 관수량을 조정하세요.",
            "low_action":  "지온 저하 — 지중 난방을 점검하세요.",
        },
        "ec_dsm": {
            "optimal":     (2.5, 4.0),
            "high_action": "EC 과다 — 청수 관수로 희석하세요.",
            "low_action":  "EC 부족 — 양액 공급을 늘리세요.",
        },
    },
    "오이": {
        "temp_internal": {
            "optimal":     (22.0, 30.0),
            "high_action": "고온 시 쓴맛 증가 및 기형과 발생. 차광·환기하세요.",
            "low_action":  "저온 시 생장 정체. 보온을 강화하세요.",
        },
        "humidity_int": {
            "optimal":     (70.0, 85.0),
            "high_action": "과습으로 노균병 발생 위험. 환기하세요.",
            "low_action":  "건조 시 흰가루병 발생 증가. 관수를 늘리세요.",
        },
        "co2_ppm": {
            "optimal":     (600.0, 1200.0),
            "high_action": "환기를 강화하세요.",
            "low_action":  "CO₂ 시비로 생산성을 높이세요.",
        },
        "soil_temp": {
            "optimal":     (18.0, 25.0),
            "high_action": "지온 과열 — 관수 조정하세요.",
            "low_action":  "지온 저하 — 지중 난방을 점검하세요.",
        },
        "ec_dsm": {
            "optimal":     (1.5, 3.0),
            "high_action": "EC 과다 — 청수 관수로 희석하세요.",
            "low_action":  "EC 부족 — 양액 농도를 높이세요.",
        },
    },
}

# 기본 범위 (farm_registry에 작목 정보 없을 때)
_DEFAULT_OPTIMAL = CROP_OPTIMAL["방울토마토"]


def _get_crop_ko(farm_id: str) -> str:
    """farm_registry에서 작목명 조회."""
    try:
        from api.data.stats_loader import _farm_registry
        reg = _farm_registry()
        info = reg.get("farms", {}).get(farm_id, {})
        return info.get("crop", info.get("crop_ko", ""))
    except Exception:
        return ""


def _cooldown_key(farm_id: str, field: str) -> str:
    return f"{farm_id}::{field}"


def _is_cooled_down(farm_id: str, field: str) -> bool:
    key  = _cooldown_key(farm_id, field)
    last = _last_notified.get(key, 0.0)
    return time.monotonic() - last >= COOLDOWN_SEC


def _mark_notified(farm_id: str, field: str) -> None:
    _last_notified[_cooldown_key(farm_id, field)] = time.monotonic()


# ── 이력 저장 ────────────────────────────────────────────────────────────────

def _append_history(
    farm_id:  str,
    crop_ko:  str,
    advices:  list[dict],
    ts:       str | None,
    channels: list[str],
) -> None:
    """advisor_history.json에 권고 이벤트 추가 (스레드 안전, 최대 _MAX_HISTORY건)."""
    event = {
        "ts":       ts or datetime.now(tz=timezone.utc).isoformat(),
        "farm_id":  farm_id,
        "crop_ko":  crop_ko,
        "channels": channels,
        "advices":  [
            {
                "field":   a["field"],
                "value":   a["value"],
                "optimal": list(a["optimal"]),
                "action":  a["action"],
                "side":    a["side"],
            }
            for a in advices
        ],
    }
    with _history_lock:
        try:
            _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            history: list[dict] = []
            if _HISTORY_PATH.exists():
                history = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
            history.append(event)
            # 최대 건수 초과 시 오래된 것 제거
            if len(history) > _MAX_HISTORY:
                history = history[-_MAX_HISTORY:]
            _HISTORY_PATH.write_text(
                json.dumps(history, ensure_ascii=False, indent=None),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("[advisor] 이력 저장 실패: %s", e)


def load_history(
    limit:   int = 50,
    farm_id: str | None = None,
    crop_ko: str | None = None,
) -> list[dict]:
    """advisor_history.json에서 최근 이력 반환."""
    with _history_lock:
        if not _HISTORY_PATH.exists():
            return []
        try:
            history: list[dict] = json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    if farm_id:
        history = [h for h in history if h.get("farm_id") == farm_id]
    if crop_ko:
        history = [h for h in history if h.get("crop_ko") == crop_ko]

    return list(reversed(history[-limit:]))


# ── 공개 API ──────────────────────────────────────────────────────────────────

def check_and_notify(payload: dict) -> list[dict]:
    """MQTT 환경 메시지를 받아 최적 범위 이탈을 감지하고 권고를 발송.

    Returns:
        발송된 권고 항목 목록 (테스트/드라이런 확인용).
    """
    farm_id = payload.get("farm_id", "unknown")
    ts      = payload.get("ts")

    # 작목 식별
    crop_ko  = _get_crop_ko(farm_id)
    optimal  = CROP_OPTIMAL.get(crop_ko, _DEFAULT_OPTIMAL)

    advices: list[dict] = []

    for field, cfg in optimal.items():
        val = payload.get(field)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue

        lo, hi = cfg["optimal"]

        # 이미 쿨다운 중이면 건너뜀
        if not _is_cooled_down(farm_id, field):
            continue

        if val > hi:
            advices.append({
                "field":   field,
                "value":   round(val, 2),
                "optimal": (lo, hi),
                "action":  cfg["high_action"],
                "side":    "high",
            })
            _mark_notified(farm_id, field)
        elif val < lo:
            advices.append({
                "field":   field,
                "value":   round(val, 2),
                "optimal": (lo, hi),
                "action":  cfg["low_action"],
                "side":    "low",
            })
            _mark_notified(farm_id, field)

    if not advices:
        return []

    if DRY_RUN:
        logger.info("[advisor] DRY-RUN farm=%s crop=%s 권고 %d건: %s",
                    farm_id, crop_ko or "미상", len(advices),
                    [(a["field"], a["value"]) for a in advices])
        return advices

    # 알림 발송
    try:
        from pipeline.notifier import notify_crop_advice
        notify_crop_advice(
            farm_id  = farm_id,
            crop_ko  = crop_ko or "작물 미상",
            advices  = advices,
            ts       = ts,
        )
        logger.info("[advisor] 권고 발송 farm=%s crop=%s 항목=%d",
                    farm_id, crop_ko, len(advices))
    except Exception as e:
        logger.error("[advisor] 권고 발송 실패: %s", e)

    return advices


def get_crop_optimal(crop_ko: str) -> dict[str, dict]:
    """작물별 최적 범위 반환 (Admin API 노출용)."""
    return CROP_OPTIMAL.get(crop_ko, _DEFAULT_OPTIMAL)


def list_supported_crops() -> list[str]:
    """최적 범위가 정의된 작목 목록."""
    return list(CROP_OPTIMAL.keys())
