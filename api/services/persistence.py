"""수동 입력 데이터 DB 영속화 서비스.

farmer.py의 인메모리 _MANUAL_ENV / _MANUAL_COSTS 딕트를
PostgreSQL manual_inputs 테이블에 저장/조회하는 계층.

테이블 스키마 (DB 초기화 스크립트에서 생성):
    manual_inputs (
        id          SERIAL PRIMARY KEY,
        farm_id     TEXT NOT NULL,
        input_type  TEXT NOT NULL,   -- 'env' | 'cost'
        payload     JSONB NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processed   BOOLEAN NOT NULL DEFAULT FALSE
    )

DB 미연결 시 인메모리 폴백 자동 사용 (개발 환경 호환).
v2
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 인메모리 폴백 저장소 ───────────────────────────────────────────────────────
_mem_env:  dict[str, dict] = {}   # farm_id → env dict
_mem_cost: dict[str, dict] = {}   # farm_id → cost dict

# ── SQLAlchemy 엔진 싱글턴 ────────────────────────────────────────────────────
_ENGINE = None
_ENGINE_FAILED = False   # 연결 실패 확정 시 True → 이후 시도 없이 즉시 None 반환


def _get_engine():
    """SQLAlchemy engine 싱글턴 반환. 실패 시 None."""
    global _ENGINE, _ENGINE_FAILED
    # 이미 연결 실패한 것으로 확인된 경우 빠르게 None 반환
    if _ENGINE_FAILED:
        return None
    if _ENGINE is not None:
        return _ENGINE
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        # pg8000 순수 Python 드라이버는 connect_timeout을 지원하지 않음 → 제외
        connect_args = {} if "pg8000" in db_url else {"connect_timeout": 3}
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            connect_args=connect_args,
        )
        with engine.connect():
            pass
        _ENGINE = engine
        logger.info("[persistence] DB 연결 성공: %s", db_url.split("@")[-1])
        return _ENGINE
    except Exception as e:
        logger.warning("[persistence] DB 연결 실패 — in-memory 폴백 사용: %s", e)
        _ENGINE_FAILED = True
        return None


# ── 환경 데이터 ────────────────────────────────────────────────────────────────

def get_manual_env(farm_id: str) -> dict:
    """최신 수동 환경 값 조회."""
    engine = _get_engine()
    if engine is None:
        return dict(_mem_env.get(farm_id, {}))
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT payload FROM manual_inputs
                    WHERE farm_id = :fid AND input_type = 'env'
                    ORDER BY recorded_at DESC LIMIT 1
                """),
                {"fid": farm_id},
            ).fetchone()
        return dict(row[0]) if row else {}
    except Exception as e:
        logger.error("[persistence] get_manual_env 오류: %s", e)
        return dict(_mem_env.get(farm_id, {}))


def set_manual_env(farm_id: str, env: dict) -> None:
    """수동 환경 값 저장."""
    engine = _get_engine()
    if engine is None:
        _mem_env[farm_id] = env
        return
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO manual_inputs (farm_id, input_type, payload, recorded_at)
                    VALUES (:fid, 'env', :payload::jsonb, NOW())
                """),
                {"fid": farm_id, "payload": json.dumps(env, ensure_ascii=False)},
            )
        _mem_env[farm_id] = env
        logger.info("[persistence] farm=%s env 저장 완료", farm_id)
    except Exception as e:
        logger.error("[persistence] set_manual_env 오류: %s — 인메모리 폴백", e)
        _mem_env[farm_id] = env


# ── 비용 데이터 ────────────────────────────────────────────────────────────────

def get_manual_cost(farm_id: str) -> dict:
    """최신 수동 비용 값 조회."""
    engine = _get_engine()
    if engine is None:
        return dict(_mem_cost.get(farm_id, {}))
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT payload FROM manual_inputs
                    WHERE farm_id = :fid AND input_type = 'cost'
                    ORDER BY recorded_at DESC LIMIT 1
                """),
                {"fid": farm_id},
            ).fetchone()
        return dict(row[0]) if row else {}
    except Exception as e:
        logger.error("[persistence] get_manual_cost 오류: %s", e)
        return dict(_mem_cost.get(farm_id, {}))


def set_manual_cost(farm_id: str, cost: dict) -> None:
    """수동 비용 값 저장."""
    engine = _get_engine()
    if engine is None:
        _mem_cost[farm_id] = cost
        return
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO manual_inputs (farm_id, input_type, payload, recorded_at)
                    VALUES (:fid, 'cost', :payload::jsonb, NOW())
                """),
                {"fid": farm_id, "payload": json.dumps(cost, ensure_ascii=False)},
            )
        _mem_cost[farm_id] = cost
        logger.info("[persistence] farm=%s cost 저장 완료", farm_id)
    except Exception as e:
        logger.error("[persistence] set_manual_cost 오류: %s — 인메모리 폴백", e)
        _mem_cost[farm_id] = cost


# ── 사용자 조회 (JWT 인증용) ──────────────────────────────────────────────────

def _get_dev_admin_hash() -> str:
    """ADMIN_PASSWORD 환경변수로 bcrypt 해시 생성. 없으면 기본값 경고 후 사용."""
    raw = os.environ.get("ADMIN_PASSWORD", "")
    if not raw:
        logger.warning(
            "[auth] ADMIN_PASSWORD 미설정 — 기본 패스워드(changeme) 사용. "
            "운영 환경에서는 반드시 변경하세요."
        )
        raw = "changeme"
    try:
        import bcrypt
        return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        return raw   # bcrypt 없을 때 평문 (개발 전용)


def get_user_by_username(username: str) -> Optional[dict]:
    """사용자 정보 조회 (users 테이블). 없으면 None."""
    engine = _get_engine()
    if engine is None:
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        _dev_users: dict[str, dict] = {
            admin_username: {
                "id": 1,
                "username": admin_username,
                "role": "admin",
                "hashed_password": _get_dev_admin_hash(),
            }
        }
        return _dev_users.get(username)

    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, role, hashed_password, farm_id FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error("[persistence] get_user_by_username 오류: %s", e)
        # DB 접속 실패 → env 기반 dev 사용자 폴백 (테스트·개발 환경 호환)
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        _dev_users: dict[str, dict] = {
            admin_username: {
                "id": 1,
                "username": admin_username,
                "role": "admin",
                "hashed_password": _get_dev_admin_hash(),
            }
        }
        return _dev_users.get(username)


# ── 헬스체크 ─────────────────────────────────────────────────────────────────

def health() -> dict[str, Any]:
    """서비스 상태 반환."""
    return {
        "db_connected":    _get_engine() is not None,
        "in_memory_farms": list(set(list(_mem_env.keys()) + list(_mem_cost.keys()))),
    }
