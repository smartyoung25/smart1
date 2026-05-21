"""MQTT 현장 테스트 시뮬레이터 — 다수 농장 센서 데이터 자동 발행.

실제 브로커가 없는 개발·현장 테스트 환경에서 smartfarm/{farm_id}/env 및
smartfarm/{farm_id}/prod 토픽으로 현실적인 센서 데이터를 연속 발행합니다.

사용:
    python -m pipeline.mqtt_simulator                    # 기본 3개 농장, 5초 간격
    python -m pipeline.mqtt_simulator --farms farm_001 farm_002
    python -m pipeline.mqtt_simulator --interval 2 --duration 60
    python -m pipeline.mqtt_simulator --anomaly          # 이상값 포함 시뮬레이션
    python -m pipeline.mqtt_simulator --dry-run          # 브로커 없이 stdout 출력만

환경변수:
    MQTT_BROKER_HOST  : 브로커 호스트 (기본: localhost)
    MQTT_BROKER_PORT  : 포트 (기본: 1883)
    MQTT_USERNAME / MQTT_PASSWORD : 인증 (선택)
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── 기본 설정 ─────────────────────────────────────────────────────────────────
_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
_USERNAME    = os.environ.get("MQTT_USERNAME", "")
_PASSWORD    = os.environ.get("MQTT_PASSWORD", "")

DEFAULT_FARMS = ["farm_001", "farm_002", "farm_003"]

# ── 작물별 기본 센서 프로파일 ─────────────────────────────────────────────────
CROP_PROFILES: dict[str, dict] = {
    "딸기": {
        "temp_internal": (18.0, 22.0),
        "humidity_int":  (75.0, 85.0),
        "co2_ppm":       (700,  900),
        "solar_rad":     (80,   200),
        "soil_temp":     (16.0, 20.0),
        "ec_dsm":        (1.5,  2.5),
        "temp_external": (5.0,  15.0),
        "humidity_ext":  (60.0, 80.0),
    },
    "토마토": {
        "temp_internal": (20.0, 26.0),
        "humidity_int":  (65.0, 80.0),
        "co2_ppm":       (800,  1100),
        "solar_rad":     (150,  350),
        "soil_temp":     (18.0, 23.0),
        "ec_dsm":        (2.0,  3.5),
        "temp_external": (10.0, 22.0),
        "humidity_ext":  (55.0, 75.0),
    },
    "파프리카": {
        "temp_internal": (22.0, 28.0),
        "humidity_int":  (70.0, 85.0),
        "co2_ppm":       (900,  1200),
        "solar_rad":     (200,  400),
        "soil_temp":     (20.0, 25.0),
        "ec_dsm":        (2.5,  4.0),
        "temp_external": (12.0, 25.0),
        "humidity_ext":  (50.0, 70.0),
    },
    "오이": {
        "temp_internal": (22.0, 27.0),
        "humidity_int":  (75.0, 90.0),
        "co2_ppm":       (700,  1000),
        "solar_rad":     (120,  280),
        "soil_temp":     (20.0, 24.0),
        "ec_dsm":        (2.0,  3.0),
        "temp_external": (10.0, 22.0),
        "humidity_ext":  (55.0, 75.0),
    },
}

# 농장별 작물 매핑
FARM_CROP_MAP: dict[str, str] = {
    "farm_001": "딸기",
    "farm_002": "토마토",
    "farm_003": "파프리카",
    "farm_004": "오이",
    "farm_005": "딸기",
}


class SensorSimulator:
    """농장 센서 데이터 시뮬레이터 — 시간대별 노이즈 + 점진적 드리프트."""

    def __init__(self, farm_id: str, include_anomaly: bool = False):
        self.farm_id       = farm_id
        self.include_anomaly = include_anomaly
        crop = FARM_CROP_MAP.get(farm_id, random.choice(list(CROP_PROFILES.keys())))
        self.crop    = crop
        self.profile = CROP_PROFILES.get(crop, CROP_PROFILES["딸기"])
        self._step   = 0
        # 각 필드별 현재값 초기화 (프로파일 중간값)
        self._state: dict[str, float] = {
            field: (lo + hi) / 2
            for field, (lo, hi) in self.profile.items()
        }

    def _hour_factor(self) -> float:
        """일중 변화 패턴 (시간대별 온도·일사량 모사)."""
        hour = datetime.now(tz=timezone.utc).hour
        # 낮(10~16시) 최대, 새벽 최소
        return 0.5 + 0.5 * math.sin(math.pi * (hour - 6) / 12)

    def next_env(self) -> dict:
        """환경 센서 페이로드 생성."""
        self._step += 1
        hf = self._hour_factor()

        payload: dict = {
            "ts":      datetime.now(tz=timezone.utc).isoformat(),
            "farm_id": self.farm_id,
        }

        # 이상값 주입 (10% 확률, include_anomaly 모드에서)
        inject_anomaly = self.include_anomaly and random.random() < 0.10

        for field, (lo, hi) in self.profile.items():
            mid   = (lo + hi) / 2
            half  = (hi - lo) / 2
            noise = random.gauss(0, half * 0.08)

            # 온도·일사량은 시간대 반영
            if "temp" in field or "solar" in field:
                base = lo + (hi - lo) * hf
            else:
                base = mid

            # 이전 값에서 점진적 변화 (smooth walk)
            prev  = self._state[field]
            value = prev * 0.85 + base * 0.15 + noise
            # 프로파일 범위에서 크게 벗어나지 않도록
            value = max(lo - half * 0.3, min(hi + half * 0.3, value))

            # 이상값 주입
            if inject_anomaly and field == random.choice(list(self.profile.keys())):
                direction = random.choice([-1, 1])
                value = (lo - half * 1.5) if direction < 0 else (hi + half * 1.5)

            self._state[field] = value
            payload[field]     = round(value, 2)

        return payload

    def next_prod(self) -> dict:
        """생육 센서 페이로드 생성."""
        base_weight = 0.3 + self._step * 0.002 + random.gauss(0, 0.05)
        return {
            "ts":               datetime.now(tz=timezone.utc).isoformat(),
            "farm_id":          self.farm_id,
            "weight_kg":        round(max(0.1, base_weight), 3),
            "fruit_count":      max(1, int(base_weight * 12 + random.gauss(0, 2))),
            "stem_length_cm":   round(random.gauss(35, 5), 1),
            "leaf_area_cm2":    round(random.gauss(120, 20), 1),
            "chlorophyll_spad": round(random.gauss(42, 4), 1),
        }


# ── MQTT 발행 ─────────────────────────────────────────────────────────────────

def _make_client(client_id: str = "smartfarm-simulator"):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        raise RuntimeError("paho-mqtt 필요: pip install paho-mqtt")

    client = mqtt.Client(client_id=client_id, clean_session=True)
    if _USERNAME:
        client.username_pw_set(_USERNAME, _PASSWORD)

    def on_connect(c, ud, flags, rc):
        if rc == 0:
            logger.info("[sim] 브로커 연결 성공: %s:%d", _BROKER_HOST, _BROKER_PORT)
        else:
            logger.error("[sim] 연결 실패 rc=%d", rc)

    def on_disconnect(c, ud, rc):
        if rc != 0:
            logger.warning("[sim] 연결 해제 rc=%d", rc)

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    return client


def run(
    farms:          list[str],
    interval_sec:   float = 5.0,
    duration_sec:   Optional[float] = None,
    include_anomaly: bool = False,
    dry_run:        bool = False,
    prod_ratio:     float = 0.2,   # 생육 데이터 발행 비율
) -> None:
    """시뮬레이션 메인 루프."""
    sims = {fid: SensorSimulator(fid, include_anomaly=include_anomaly) for fid in farms}

    client = None
    if not dry_run:
        client = _make_client()
        try:
            client.connect(_BROKER_HOST, _BROKER_PORT, keepalive=60)
            client.loop_start()
        except Exception as e:
            logger.error("[sim] 브로커 연결 실패: %s — dry-run 모드로 전환", e)
            client = None

    logger.info("[sim] 시뮬레이션 시작 — 농장: %s | 간격: %.1f초 | 이상값: %s",
                farms, interval_sec, include_anomaly)

    start = time.monotonic()
    tick  = 0

    try:
        while True:
            elapsed = time.monotonic() - start
            if duration_sec and elapsed >= duration_sec:
                logger.info("[sim] 종료 (%.0f초 경과)", elapsed)
                break

            for farm_id, sim in sims.items():
                # 환경 센서
                env_payload = sim.next_env()
                topic_env   = f"smartfarm/{farm_id}/env"
                msg         = json.dumps(env_payload, ensure_ascii=False)

                if client:
                    client.publish(topic_env, msg, qos=1)
                if dry_run or logger.isEnabledFor(logging.DEBUG):
                    print(f"[{topic_env}] {msg}")

                # 생육 센서 (일부만)
                if random.random() < prod_ratio:
                    prod_payload = sim.next_prod()
                    topic_prod   = f"smartfarm/{farm_id}/prod"
                    msg_prod     = json.dumps(prod_payload, ensure_ascii=False)
                    if client:
                        client.publish(topic_prod, msg_prod, qos=1)
                    if dry_run or logger.isEnabledFor(logging.DEBUG):
                        print(f"[{topic_prod}] {msg_prod}")

            tick += 1
            if tick % 10 == 0:
                logger.info("[sim] %d 사이클 완료 (%.0f초 경과)", tick, elapsed)

            time.sleep(interval_sec)

    except KeyboardInterrupt:
        logger.info("[sim] 사용자 중단")
    finally:
        if client:
            client.loop_stop()
            client.disconnect()
        logger.info("[sim] 시뮬레이터 종료")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Smart Farm MQTT 시뮬레이터")
    parser.add_argument("--farms",    nargs="+", default=DEFAULT_FARMS,
                        help="시뮬레이션할 농장 ID 목록")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="발행 간격 (초, 기본 5)")
    parser.add_argument("--duration", type=float, default=None,
                        help="실행 시간 (초, 기본 무한)")
    parser.add_argument("--anomaly",  action="store_true",
                        help="이상값 주입 (10% 확률)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="브로커 없이 stdout 출력만")
    parser.add_argument("--host",     default=None)
    parser.add_argument("--port",     default=None, type=int)
    args = parser.parse_args()

    global _BROKER_HOST, _BROKER_PORT
    if args.host: _BROKER_HOST = args.host
    if args.port: _BROKER_PORT = args.port

    run(
        farms           = args.farms,
        interval_sec    = args.interval,
        duration_sec    = args.duration,
        include_anomaly = args.anomaly,
        dry_run         = args.dry_run,
    )


if __name__ == "__main__":
    _main()
