"""MQTT 구독자 — 스마트팜 IoT 센서 실시간 수집.

농장 센서 → MQTT Broker → 이 스크립트 → ETL CSV 누적 저장
                                        → WebSocket 브로드캐스트 (인메모리 버퍼)

토픽 구조:
    smartfarm/{farm_id}/env    : 환경 센서 (온도, 습도, CO2, 일사량 ...)
    smartfarm/{farm_id}/prod   : 생육/수확량 센서
    smartfarm/+/env            : 전체 농장 환경 구독 (와일드카드)

페이로드 형식 (JSON):
    {
        "ts":           "2026-05-16T07:00:00Z",   // ISO-8601 UTC
        "farm_id":      "farm_001",
        "temp_internal": 22.5,
        "humidity_int":  75.0,
        "co2_ppm":       800,
        "solar_rad":     120.5,
        "soil_temp":     20.1,
        "ec_dsm":        2.1
    }

환경변수:
    MQTT_BROKER_HOST  : 브로커 호스트 (기본: localhost)
    MQTT_BROKER_PORT  : 포트 (기본: 1883)
    MQTT_USERNAME     : 인증 사용자명 (선택)
    MQTT_PASSWORD     : 인증 패스워드 (선택)
    MQTT_CLIENT_ID    : 클라이언트 ID (기본: smartfarm-subscriber)
    MQTT_KEEPALIVE    : Keepalive 초 (기본: 60)
    ETL_DATA_DIR      : ETL 입력 디렉터리 (기본: ./etl_data)
    MQTT_BUFFER_SIZE  : 인메모리 버퍼 크기 (기본: 500)

사용:
    python -m pipeline.mqtt_subscriber
    python -m pipeline.mqtt_subscriber --dry-run   # 메시지 출력만, CSV 저장 안 함
"""
from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT        = Path(__file__).parent.parent
ETL_DIR     = Path(os.environ.get("ETL_DATA_DIR", str(ROOT / "etl_data")))

# ── MQTT 설정 ─────────────────────────────────────────────────────────────────
_BROKER_HOST  = os.environ.get("MQTT_BROKER_HOST", "localhost")
_BROKER_PORT  = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
_USERNAME     = os.environ.get("MQTT_USERNAME", "")
_PASSWORD     = os.environ.get("MQTT_PASSWORD", "")
_CLIENT_ID    = os.environ.get("MQTT_CLIENT_ID", "smartfarm-subscriber")
_KEEPALIVE    = int(os.environ.get("MQTT_KEEPALIVE", "60"))
_BUFFER_SIZE  = int(os.environ.get("MQTT_BUFFER_SIZE", "500"))

# ── 토픽 ─────────────────────────────────────────────────────────────────────
TOPICS_ENV  = "smartfarm/+/env"
TOPICS_PROD = "smartfarm/+/prod"
QOS         = 1

# ── 센서 필드 정의 ────────────────────────────────────────────────────────────
ENV_FIELDS = [
    "ts", "farm_id",
    "temp_internal", "humidity_int", "co2_ppm",
    "solar_rad", "soil_temp", "ec_dsm",
    "temp_external", "humidity_ext",
]
PROD_FIELDS = [
    "ts", "farm_id",
    "weight_kg", "fruit_count", "stem_length_cm",
    "leaf_area_cm2", "chlorophyll_spad",
]

# 유효 범위 (이상값 필터링)
_ENV_RANGE: dict[str, tuple[float, float]] = {
    "temp_internal":  (-5.0,  55.0),
    "humidity_int":   (0.0,   100.0),
    "co2_ppm":        (200.0, 5000.0),
    "solar_rad":      (0.0,   1500.0),
    "soil_temp":      (-5.0,  50.0),
    "ec_dsm":         (0.0,   10.0),
    "temp_external":  (-30.0, 50.0),
    "humidity_ext":   (0.0,   100.0),
}

# ── 인메모리 버퍼 (WebSocket 브로드캐스트용) ──────────────────────────────────
_buffer: deque[dict] = deque(maxlen=_BUFFER_SIZE)
_buffer_lock = threading.Lock()

# 연결된 WebSocket 콜백 등록
_ws_callbacks: list = []
_ws_lock = threading.Lock()


def register_ws_callback(callback) -> None:
    """WebSocket 라우터에서 실시간 데이터 수신 콜백 등록."""
    with _ws_lock:
        _ws_callbacks.append(callback)


def unregister_ws_callback(callback) -> None:
    with _ws_lock:
        try:
            _ws_callbacks.remove(callback)
        except ValueError:
            pass


def get_recent_messages(farm_id: Optional[str] = None, n: int = 50) -> list[dict]:
    """최근 N개 메시지 반환 (farm_id 필터 선택)."""
    with _buffer_lock:
        msgs = list(_buffer)
    if farm_id:
        msgs = [m for m in msgs if m.get("farm_id") == farm_id]
    return msgs[-n:]


# ── 이상값 알림 속도 제한 (farm별 마지막 알림 시각) ──────────────────────────────
_anomaly_last_notified: dict[str, float] = {}
_ANOMALY_NOTIFY_COOLDOWN = 300  # 초 (5분)


def _maybe_notify_anomaly(farm_id: str, payload: dict) -> None:
    """이상값 알림 발송 — 동일 농장 5분 이내 중복 발송 방지."""
    import time
    now = time.monotonic()
    last = _anomaly_last_notified.get(farm_id, 0)
    if now - last < _ANOMALY_NOTIFY_COOLDOWN:
        return   # 쿨다운 중

    # 이상 항목 목록 구성
    anomaly_list = []
    for field, (lo, hi) in _ENV_RANGE.items():
        val = payload.get(field)
        if val is not None and not (lo <= float(val) <= hi):
            anomaly_list.append({"field": field, "value": float(val), "range": (lo, hi)})

    if not anomaly_list:
        return

    try:
        from pipeline.notifier import notify_sensor_anomaly
        notify_sensor_anomaly(
            farm_id=farm_id,
            anomalies=anomaly_list,
            ts=payload.get("ts"),
        )
        _anomaly_last_notified[farm_id] = now
    except Exception as e:
        logger.warning("[mqtt] 이상값 알림 발송 실패: %s", e)


# ── 이상값 필터 ───────────────────────────────────────────────────────────────

def _validate_env(payload: dict) -> tuple[bool, list[str]]:
    """환경 센서 값 유효성 검사. (valid, [이상 필드]) 반환."""
    anomalies = []
    for field, (lo, hi) in _ENV_RANGE.items():
        val = payload.get(field)
        if val is not None and not (lo <= float(val) <= hi):
            anomalies.append(f"{field}={val} (범위 {lo}~{hi})")
    return len(anomalies) == 0, anomalies


# ── CSV 저장 ──────────────────────────────────────────────────────────────────

def _csv_path(farm_id: str, data_type: str) -> Path:
    """ETL 입력 CSV 경로 — 하루 단위 파일 (파일명: {farm_id}__{crop}__{season}__{type}.csv)."""
    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    # 농장별 작목은 farm_registry 조회, 없으면 unknown
    try:
        from api.data.stats_loader import _farm_registry
        reg = _farm_registry()
        farm_info = reg.get("farms", {}).get(farm_id, {})
        crop   = farm_info.get("crop_ko", "unknown").replace(" ", "_")
        season = farm_info.get("season", today[:4])
    except Exception:
        crop   = "unknown"
        season = today[:4]

    fname = f"{farm_id}__{crop}__{season}__{data_type}__{today}.csv"
    return ETL_DIR / "incoming" / fname


def _append_csv(path: Path, row: dict, fields: list[str]) -> None:
    """CSV 파일에 행 추가 (없으면 헤더 포함 생성)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ── 메시지 처리 ───────────────────────────────────────────────────────────────

def _process_env(payload: dict, dry_run: bool = False) -> None:
    farm_id = payload.get("farm_id", "unknown")
    valid, anomaly_descs = _validate_env(payload)

    if not valid:
        logger.warning("[mqtt] 이상값 감지 farm=%s: %s", farm_id, ", ".join(anomaly_descs))
        payload["_anomaly"] = True

        # Slack/이메일 즉시 알림 (속도 제한: 동일 농장 5분 이내 중복 발송 방지)
        _maybe_notify_anomaly(farm_id, payload)

    # 타임스탬프 보정
    if "ts" not in payload:
        payload["ts"] = datetime.now(tz=timezone.utc).isoformat()

    # 인메모리 버퍼 저장
    msg = {"type": "env", **payload}
    with _buffer_lock:
        _buffer.append(msg)

    # WebSocket 콜백 브로드캐스트
    with _ws_lock:
        dead = []
        for cb in _ws_callbacks:
            try:
                cb(msg)
            except Exception:
                dead.append(cb)
        for cb in dead:
            _ws_callbacks.remove(cb)

    # 재배 최적화 권고 (이상값과 별개 — 작물별 최적 범위 이탈 시 이메일/SMS/카카오)
    if valid and not dry_run:
        try:
            from pipeline.crop_advisor import check_and_notify
            check_and_notify(payload)
        except Exception as e:
            logger.debug("[mqtt] crop_advisor 호출 실패: %s", e)

    # CSV 저장
    if not dry_run and valid:
        path = _csv_path(farm_id, "env")
        try:
            _append_csv(path, payload, ENV_FIELDS)
        except Exception as e:
            logger.error("[mqtt] CSV 저장 실패 %s: %s", path, e)


def _process_prod(payload: dict, dry_run: bool = False) -> None:
    farm_id = payload.get("farm_id", "unknown")
    if "ts" not in payload:
        payload["ts"] = datetime.now(tz=timezone.utc).isoformat()

    msg = {"type": "prod", **payload}
    with _buffer_lock:
        _buffer.append(msg)

    if not dry_run:
        path = _csv_path(farm_id, "prod")
        try:
            _append_csv(path, payload, PROD_FIELDS)
        except Exception as e:
            logger.error("[mqtt] CSV 저장 실패 %s: %s", path, e)


# ── MQTT 클라이언트 ───────────────────────────────────────────────────────────

def _make_client(dry_run: bool = False):
    """paho-mqtt 클라이언트 생성 및 콜백 등록."""
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        raise RuntimeError(
            "paho-mqtt 패키지가 필요합니다: pip install paho-mqtt"
        )

    client = mqtt.Client(client_id=_CLIENT_ID, clean_session=True)

    if _USERNAME:
        client.username_pw_set(_USERNAME, _PASSWORD)

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            logger.info("[mqtt] 브로커 연결 성공: %s:%d", _BROKER_HOST, _BROKER_PORT)
            c.subscribe([(TOPICS_ENV, QOS), (TOPICS_PROD, QOS)])
            logger.info("[mqtt] 구독: %s, %s", TOPICS_ENV, TOPICS_PROD)
        else:
            logger.error("[mqtt] 연결 실패 rc=%d", rc)

    def on_disconnect(c, userdata, rc):
        if rc != 0:
            logger.warning("[mqtt] 예상치 못한 연결 해제 (rc=%d) — 재연결 대기", rc)

    def on_message(c, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.warning("[mqtt] 페이로드 파싱 실패 topic=%s: %s", msg.topic, e)
            return

        topic = msg.topic
        if "/env" in topic:
            _process_env(payload, dry_run=dry_run)
        elif "/prod" in topic:
            _process_prod(payload, dry_run=dry_run)
        else:
            logger.debug("[mqtt] 알 수 없는 토픽: %s", topic)

        if dry_run:
            print(f"[DRY-RUN] {topic}: {json.dumps(payload, ensure_ascii=False)}")

    def on_log(c, userdata, level, buf):
        if level in (16,):   # MQTT_LOG_ERR
            logger.error("[mqtt-lib] %s", buf)

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message
    client.on_log        = on_log

    # TLS (환경변수로 선택)
    tls_ca = os.environ.get("MQTT_TLS_CA")
    if tls_ca:
        client.tls_set(ca_certs=tls_ca)
        logger.info("[mqtt] TLS 활성화")

    return client


def run(dry_run: bool = False) -> None:
    """MQTT 구독자 메인 루프 (블로킹)."""
    client = _make_client(dry_run=dry_run)

    reconnect_delay = 5
    while True:
        try:
            client.connect(_BROKER_HOST, _BROKER_PORT, keepalive=_KEEPALIVE)
            client.loop_forever()
        except Exception as e:
            logger.error("[mqtt] 연결 오류: %s — %d초 후 재시도", e, reconnect_delay)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 120)   # 최대 2분


# ── CLI 진입점 ────────────────────────────────────────────────────────────────

def _main() -> None:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Smart Farm MQTT 구독자")
    parser.add_argument("--dry-run", action="store_true",
                        help="메시지 출력만, CSV 저장 안 함")
    parser.add_argument("--host",    default=None, help="브로커 호스트 override")
    parser.add_argument("--port",    default=None, type=int, help="브로커 포트 override")
    args = parser.parse_args()

    global _BROKER_HOST, _BROKER_PORT
    if args.host: _BROKER_HOST = args.host
    if args.port: _BROKER_PORT = args.port

    logger.info("MQTT 구독자 시작 — 브로커: %s:%d", _BROKER_HOST, _BROKER_PORT)
    if args.dry_run:
        logger.info("[DRY-RUN] CSV 저장 비활성화")

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    _main()
