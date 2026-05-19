"""WebSocket 라우터 — 실시간 센서 데이터 스트리밍.

엔드포인트:
    ws://{host}/ws/farms/{farm_id}/sensors
        → 해당 농장의 실시간 MQTT 센서 데이터 수신

    GET /api/sensors/{farm_id}/latest
        → 최근 N개 센서 메시지 (HTTP polling 폴백)

    GET /api/sensors/{farm_id}/status
        → 현재 연결 수 및 마지막 수신 시각

프로토콜:
    서버 → 클라이언트: JSON 메시지 스트리밍
    {
        "type":         "env",
        "farm_id":      "farm_001",
        "ts":           "2026-05-16T07:00:00Z",
        "temp_internal": 22.5,
        ...
    }

    클라이언트 → 서버: ping (연결 유지)
    {"type": "ping"}   → {"type": "pong"}
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

# ── 연결 관리자 ───────────────────────────────────────────────────────────────

class ConnectionManager:
    """WebSocket 연결 풀 — 농장별 구독자 관리."""

    def __init__(self):
        # farm_id → set of WebSocket
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._last_seen: dict[str, str] = {}     # farm_id → 마지막 메시지 ts

    async def connect(self, ws: WebSocket, farm_id: str) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[farm_id].add(ws)
        logger.info("[ws] 연결: farm=%s (총 %d개)", farm_id, self.count(farm_id))

    async def disconnect(self, ws: WebSocket, farm_id: str) -> None:
        async with self._lock:
            self._connections[farm_id].discard(ws)
        logger.info("[ws] 해제: farm=%s (총 %d개)", farm_id, self.count(farm_id))

    def count(self, farm_id: Optional[str] = None) -> int:
        if farm_id:
            return len(self._connections.get(farm_id, set()))
        return sum(len(s) for s in self._connections.values())

    async def broadcast(self, farm_id: str, message: dict) -> None:
        """특정 농장 구독자 전체에게 메시지 전송."""
        self._last_seen[farm_id] = message.get("ts", datetime.now(tz=timezone.utc).isoformat())
        dead = set()
        payload = json.dumps(message, ensure_ascii=False, default=str)

        for ws in list(self._connections.get(farm_id, set())):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)

        if dead:
            async with self._lock:
                self._connections[farm_id] -= dead

    async def broadcast_all(self, message: dict) -> None:
        """모든 농장 구독자에게 메시지 전송 (farm_id 매칭)."""
        farm_id = message.get("farm_id")
        if farm_id:
            await self.broadcast(farm_id, message)

    def get_status(self, farm_id: str) -> dict:
        return {
            "farm_id":      farm_id,
            "connections":  self.count(farm_id),
            "last_seen_ts": self._last_seen.get(farm_id),
        }


manager = ConnectionManager()


# ── MQTT → WebSocket 브리지 ──────────────────────────────────────────────────

def _setup_mqtt_bridge() -> None:
    """MQTT 구독자의 콜백으로 WebSocket 브로드캐스트 연결.

    main.py 시작 시 한 번 호출됩니다.
    루프가 없는 환경(테스트)에서는 조용히 무시됩니다.
    """
    try:
        from pipeline.mqtt_subscriber import register_ws_callback

        def _sync_callback(msg: dict) -> None:
            """MQTT 스레드에서 asyncio 이벤트 루프로 태스크 전달.

            env 타입 메시지에 이상치 탐지 결과(_anomaly, _alerts)를 추가한다.
            """
            enriched = msg
            if msg.get("type") == "env":
                try:
                    from api.services.anomaly_detector import detect_anomalies
                    _ENV_KEYS = {"temp_internal", "humidity_int", "co2_ppm",
                                 "solar_rad", "ec_dsm", "soil_temp"}
                    env_vals = {k: float(v) for k, v in msg.items()
                                if k in _ENV_KEYS and v is not None}
                    crop_ko = msg.get("crop_ko", "딸기")
                    alerts = detect_anomalies(crop_ko, env_vals)
                    enriched = {
                        **msg,
                        "_anomaly": bool(alerts),
                        "_alerts": [
                            {"variable": a.variable, "severity": a.severity,
                             "message_ko": a.message_ko}
                            for a in alerts
                        ],
                    }
                except Exception:
                    pass

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(
                        lambda m=enriched: asyncio.ensure_future(manager.broadcast_all(m))
                    )
            except RuntimeError:
                pass   # 루프 없음 (테스트/CLI 환경)

        register_ws_callback(_sync_callback)
        logger.info("[ws] MQTT→WebSocket 브리지 등록 완료")
    except Exception as e:
        logger.warning("[ws] MQTT 브리지 등록 실패 (MQTT 비활성 환경): %s", e)


# ── WebSocket 엔드포인트 ──────────────────────────────────────────────────────

@router.websocket("/ws/farms/{farm_id}/sensors")
async def ws_sensor_stream(websocket: WebSocket, farm_id: str):
    """실시간 센서 스트리밍 WebSocket.

    연결 직후 최근 20개 메시지를 일괄 전송 후
    이후 MQTT에서 수신되는 메시지를 실시간으로 푸시합니다.
    """
    await manager.connect(websocket, farm_id)
    try:
        # 연결 직후 최근 캐시 전송
        try:
            from pipeline.mqtt_subscriber import get_recent_messages
            history = get_recent_messages(farm_id=farm_id, n=20)
            if history:
                await websocket.send_text(json.dumps({
                    "type":     "history",
                    "farm_id":  farm_id,
                    "messages": history,
                }, ensure_ascii=False, default=str))
        except Exception:
            pass   # MQTT 구독자 미실행 환경

        # 메시지 수신 루프 (ping/pong 처리)
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "ts":   datetime.now(tz=timezone.utc).isoformat(),
                    }))
            except asyncio.TimeoutError:
                # 30초마다 heartbeat 전송
                await websocket.send_text(json.dumps({
                    "type": "heartbeat",
                    "ts":   datetime.now(tz=timezone.utc).isoformat(),
                    "connections": manager.count(farm_id),
                }))
            except (WebSocketDisconnect, RuntimeError):
                break

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, farm_id)


# ── HTTP 폴백 엔드포인트 ──────────────────────────────────────────────────────

class SensorMessage(BaseModel):
    type:           str
    farm_id:        str
    ts:             str
    temp_internal:  Optional[float] = None
    humidity_int:   Optional[float] = None
    co2_ppm:        Optional[float] = None
    solar_rad:      Optional[float] = None
    soil_temp:      Optional[float] = None
    ec_dsm:         Optional[float] = None


class SensorLatestResponse(BaseModel):
    farm_id:  str
    messages: list[dict]
    count:    int
    source:   str


class SensorStatusResponse(BaseModel):
    farm_id:      str
    connections:  int
    last_seen_ts: Optional[str]
    mqtt_active:  bool


@router.get(
    "/api/sensors/{farm_id}/latest",
    response_model=SensorLatestResponse,
    tags=["realtime"],
    summary="최근 센서 데이터 조회 (HTTP 폴백)",
)
def get_latest_sensor(
    farm_id: str,
    n: int = Query(default=20, ge=1, le=200, description="반환 메시지 수"),
):
    """WebSocket을 사용할 수 없는 클라이언트를 위한 HTTP 폴링 엔드포인트."""
    try:
        from pipeline.mqtt_subscriber import get_recent_messages
        messages = get_recent_messages(farm_id=farm_id, n=n)
        source = "mqtt_buffer"
    except Exception:
        messages = []
        source   = "unavailable"

    return SensorLatestResponse(
        farm_id=farm_id,
        messages=messages,
        count=len(messages),
        source=source,
    )


@router.get(
    "/api/sensors/{farm_id}/status",
    response_model=SensorStatusResponse,
    tags=["realtime"],
    summary="센서 스트림 연결 상태",
)
def get_sensor_status(farm_id: str):
    """현재 WebSocket 연결 수와 마지막 수신 시각."""
    mqtt_active = False
    try:
        import pipeline.mqtt_subscriber   # noqa: F401
        mqtt_active = True
    except Exception:
        pass

    status = manager.get_status(farm_id)
    return SensorStatusResponse(
        farm_id=farm_id,
        connections=status["connections"],
        last_seen_ts=status["last_seen_ts"],
        mqtt_active=mqtt_active,
    )
