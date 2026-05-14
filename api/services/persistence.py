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
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 인메모리 폴백 저장소 ───────────────────────────────────────────────────────
_mem_env:  dict[str, dict]  = {}   # farm_id → env dict
_mem_cost: dict[str, dict]  = {}   # farm_id → cost dict


def _get_engine():
    """SQLAlchemy engine 반환. 실패 시 None."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return None
    try:
        from sqlalchemy import create_engine
        return create_engine(db_url, pool_pre_ping=True, pool_size=3)
    except Exception as e:
        logger.warning("[persistence] DB 연결 실패: %s", e)
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
        logger.info("[persistence] farm=%s cost 저장 완료", farm_id)
    except Exception as e:
        logger.error("[persistence] set_manual_cost 오류: %s — 인메모리 폴백", e)
        _mem_cost[farm_id] = cost


# ── 인증 토큰 발급 엔드포인트용 사용자 조회 ────────────────────────────────────

def get_user_by_username(username: str) -> Optional[dict]:
    """사용자 정보 조회 (users 테이블). 없으면 None."""
    engine = _get_engine()
    if engine is None:
        # 개발용 하드코딩 테스트 계정
        _dev_users = {
            "admin": {"id": 1, "username": "admin", "role": "admin",
                      "hashed_password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"},  # "secret"
        }
        return _dev_users.get(username)

    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, role, hashed_password FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error("[persistence] get_user_by_username 오류: %s", e)
        return None
