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
v3
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 인메모리 폴백 저장소 ───────────────────────────────────────────────────────
_mem_env:  dict[str, dict] = {}   # farm_id → env dict
_mem_cost: dict[str, dict] = {}   # farm_id → cost dict
_mem_onboarding: dict[int, dict] = {}   # user_id → onboarding dict
_mem_users: dict[str, dict] = {}        # username → user dict (회원가입 폴백)

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


def get_env_history(farm_id: str, limit: int = 20) -> list:
    """수동 환경값 입력 이력 조회 (최신순)."""
    engine = _get_engine()
    if engine is None:
        item = _mem_env.get(farm_id)
        return [{"payload": item, "recorded_at": None}] if item else []
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT payload, recorded_at FROM manual_inputs
                    WHERE farm_id = :fid AND input_type = 'env'
                    ORDER BY recorded_at DESC LIMIT :lim
                """),
                {"fid": farm_id, "lim": limit},
            ).fetchall()
        return [{"payload": dict(r[0]), "recorded_at": str(r[1])} for r in rows]
    except Exception as e:
        logger.error("[persistence] get_env_history 오류: %s", e)
        item = _mem_env.get(farm_id)
        return [{"payload": item, "recorded_at": None}] if item else []


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
                text("SELECT id, username, role, hashed_password, farm_id, onboarding_completed FROM users WHERE username = :u"),
                {"u": username},
            ).fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error("[persistence] get_user_by_username 오류: %s", e)
        # DB 접속 실패 → env 기반 dev 사용자 폴백 (테스트·개발 환경 호환)
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


def get_user_by_email(email: str) -> Optional[dict]:
    """이메일로 사용자 조회. 없으면 None. (비밀번호 찾기용)"""
    if not email:
        return None
    engine = _get_engine()
    if engine is None:
        for u in _mem_users.values():
            if u.get("email", "").lower() == email.lower():
                return u
        return None
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, username, role, email, farm_id FROM users WHERE email = :e"),
                {"e": email},
            ).fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error("[persistence] get_user_by_email 오류: %s", e)
        return None


def set_user_password(username: str, hashed_password: str) -> bool:
    """사용자 비밀번호 변경. 성공 시 True. (비밀번호 재설정용)"""
    engine = _get_engine()
    if engine is None:
        u = _mem_users.get(username)
        if not u:
            return False
        u["hashed_password"] = hashed_password
        return True
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            res = conn.execute(
                text("UPDATE users SET hashed_password = :hp WHERE username = :u"),
                {"hp": hashed_password, "u": username},
            )
        return (res.rowcount or 0) > 0
    except Exception as e:
        logger.error("[persistence] set_user_password 오류: %s", e)
        return False


# ── 회원가입 ─────────────────────────────────────────────────────────────────

def create_user(
    username: str,
    hashed_password: str,
    name: str = "",
    email: str = "",
    phone: str = "",
    role: str = "farmer",
) -> dict:
    """신규 사용자 생성. 생성된 사용자 dict 반환. 중복 시 ValueError."""
    safe = re.sub(r"[^a-z0-9_]", "", username.lower())[:16] or "user"
    engine = _get_engine()

    # ── 인메모리 폴백 ──────────────────────────────────────────────────────────
    if engine is None:
        if username in _mem_users:
            raise ValueError(f"이미 사용 중인 사용자명입니다: {username}")
        new_id = max((u["id"] for u in _mem_users.values()), default=100) + 1
        farm_id = f"farm_{safe}"
        user = {
            "id": new_id, "username": username,
            "hashed_password": hashed_password,
            "name": name, "email": email, "phone": phone,
            "role": role, "farm_id": farm_id,
            "onboarding_completed": False,
        }
        _mem_users[username] = user
        return user

    # ── DB 경로 ────────────────────────────────────────────────────────────────
    # phone 컬럼 존재 여부 사전 확인 (별도 트랜잭션 — ALTER 권한 없어도 가입 실패 방지).
    # 컬럼이 없고 권한이 있으면 best-effort 보강, 없으면 컬럼 없이 INSERT하고
    # 전화번호는 사이드 파일에 보존한다.
    _has_phone_col = False
    try:
        from sqlalchemy import text as _t
        with engine.connect() as _c:
            _has_phone_col = bool(_c.execute(_t(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='users' AND column_name='phone'")).fetchone())
        if not _has_phone_col:
            try:
                with engine.begin() as _c2:
                    _c2.execute(_t("ALTER TABLE users ADD COLUMN phone VARCHAR(32)"))
                _has_phone_col = True
            except Exception as _e:
                logger.info("[persistence] phone 컬럼 보강 권한 없음 — 사이드 파일 사용: %s",
                            str(_e)[:80])
    except Exception as _e:
        logger.warning("[persistence] phone 컬럼 확인 실패: %s", str(_e)[:80])

    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            if conn.execute(text("SELECT id FROM users WHERE username = :u"), {"u": username}).fetchone():
                raise ValueError(f"이미 사용 중인 사용자명입니다: {username}")
            if email and conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email}).fetchone():
                raise ValueError("이미 사용 중인 이메일입니다.")

            if _has_phone_col:
                row = conn.execute(
                    text("""
                        INSERT INTO users (username, hashed_password, name, email, phone, role, onboarding_completed)
                        VALUES (:u, :hp, :n, :e, :ph, :r, FALSE)
                        RETURNING id
                    """),
                    {"u": username, "hp": hashed_password, "n": name, "e": email or None,
                     "ph": phone or None, "r": role},
                ).fetchone()
            else:
                row = conn.execute(
                    text("""
                        INSERT INTO users (username, hashed_password, name, email, role, onboarding_completed)
                        VALUES (:u, :hp, :n, :e, :r, FALSE)
                        RETURNING id
                    """),
                    {"u": username, "hp": hashed_password, "n": name, "e": email or None, "r": role},
                ).fetchone()
            # 전화번호 사이드 파일 보존 (컬럼 유무와 무관하게 항상 기록)
            if phone:
                try:
                    _cp = Path(__file__).resolve().parents[1] / "data" / "user_contacts.json"
                    _store = json.loads(_cp.read_text(encoding="utf-8")) if _cp.exists() else {}
                    _store[username] = {"phone": phone, "email": email}
                    _cp.write_text(json.dumps(_store, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as _e:
                    logger.warning("[persistence] 연락처 사이드 저장 실패: %s", str(_e)[:80])
            user_id = row[0]
            farm_id = f"farm_{safe}"

            # farms 테이블에 row가 없으면 먼저 생성 (FK 제약 충족)
            # tier: 'manual' | 'semi_auto' | 'auto'  (farms_tier_check 제약)
            farm_exists = conn.execute(
                text("SELECT 1 FROM farms WHERE farm_id = :fid"), {"fid": farm_id}
            ).fetchone()
            if not farm_exists:
                conn.execute(
                    text("""
                        INSERT INTO farms (farm_id, name, crop_type, region, tier)
                        VALUES (:fid, :nm, :ct, :reg, 'manual')
                        ON CONFLICT (farm_id) DO NOTHING
                    """),
                    {"fid": farm_id, "nm": name or username, "ct": "미설정", "reg": None},
                )
            conn.execute(
                text("UPDATE users SET farm_id = :fid WHERE id = :uid"),
                {"fid": farm_id, "uid": user_id},
            )
        logger.info("[persistence] 신규 사용자 생성: %s (id=%d, farm=%s)", username, user_id, farm_id)
        return {
            "id": user_id, "username": username,
            "role": role, "farm_id": farm_id,
            "onboarding_completed": False,
        }
    except ValueError:
        raise
    except Exception as e:
        logger.error("[persistence] create_user 오류: %s", e)
        raise


# ── 온보딩 ────────────────────────────────────────────────────────────────────

def save_onboarding(user_id: int, farm_id: str, data: dict) -> None:
    """온보딩 데이터 저장 및 onboarding_completed 플래그 TRUE 설정."""
    # 전체 온보딩 데이터 사이드 파일 보존(DB 컬럼 미존재 필드 — irrigation_method·
    # farm_name·sido/sigungu/emd·cultivation_detail 등 — 누락 방지)
    try:
        _op = Path(__file__).resolve().parents[1] / "data" / "onboarding"
        _op.mkdir(parents=True, exist_ok=True)
        (_op / f"{farm_id}.json").write_text(
            json.dumps({"user_id": user_id, "farm_id": farm_id, **data}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception as _e:
        logger.warning("[persistence] 온보딩 사이드 저장 실패: %s", str(_e)[:80])

    engine = _get_engine()
    if engine is None:
        _mem_onboarding[user_id] = {"farm_id": farm_id, **data}
        return

    try:
        from sqlalchemy import text
        params = {
            "uid":   user_id,
            "fid":   farm_id,
            "crop_ko":            data.get("crop_ko"),
            "facility_type":      data.get("facility_type"),
            "area_m2":            data.get("area_m2"),
            "cultivation_method": data.get("cultivation_method", "토경"),
            "region":             data.get("region"),
            "season_start":       data.get("season_start") or None,
            "season_end":         data.get("season_end")   or None,
            "growing_year":       data.get("growing_year", 1),
            "pain_points":        json.dumps(data.get("pain_points", []), ensure_ascii=False),
            "kpi_yield_kg":       data.get("kpi_yield_kg"),
            "kpi_revenue_wan":    data.get("kpi_revenue_wan"),
            "kpi_energy_save":    data.get("kpi_energy_save"),
            "kpi_drain_rate":     data.get("kpi_drain_rate"),
        }
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id FROM user_onboarding WHERE user_id = :uid"), {"uid": user_id}
            ).fetchone()
            if existing:
                conn.execute(text("""
                    UPDATE user_onboarding SET
                        farm_id=:fid, crop_ko=:crop_ko, facility_type=:facility_type,
                        area_m2=:area_m2, cultivation_method=:cultivation_method,
                        region=:region, season_start=:season_start, season_end=:season_end,
                        growing_year=:growing_year,
                        pain_points=CAST(:pain_points AS jsonb),
                        kpi_yield_kg=:kpi_yield_kg, kpi_revenue_wan=:kpi_revenue_wan,
                        kpi_energy_save=:kpi_energy_save, kpi_drain_rate=:kpi_drain_rate,
                        completed_at=NOW()
                    WHERE user_id=:uid
                """), params)
            else:
                conn.execute(text("""
                    INSERT INTO user_onboarding (
                        user_id, farm_id, crop_ko, facility_type, area_m2,
                        cultivation_method, region, season_start, season_end, growing_year,
                        pain_points, kpi_yield_kg, kpi_revenue_wan, kpi_energy_save, kpi_drain_rate
                    ) VALUES (
                        :uid, :fid, :crop_ko, :facility_type, :area_m2,
                        :cultivation_method, :region, :season_start, :season_end, :growing_year,
                        CAST(:pain_points AS jsonb), :kpi_yield_kg, :kpi_revenue_wan,
                        :kpi_energy_save, :kpi_drain_rate
                    )
                """), params)
            conn.execute(
                text("UPDATE users SET onboarding_completed = TRUE WHERE id = :uid"),
                {"uid": user_id},
            )
        logger.info("[persistence] user_id=%d 온보딩 저장 완료", user_id)
    except Exception as e:
        logger.error("[persistence] save_onboarding 오류: %s", e)
        raise


def get_onboarding(user_id: int) -> Optional[dict]:
    """온보딩 데이터 조회. 없으면 None."""
    engine = _get_engine()
    if engine is None:
        return _mem_onboarding.get(user_id)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM user_onboarding WHERE user_id = :uid"), {"uid": user_id}
            ).fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error("[persistence] get_onboarding 오류: %s", e)
        return None


# ── 헬스체크 ─────────────────────────────────────────────────────────────────

def health() -> dict[str, Any]:
    """서비스 상태 반환."""
    return {
        "db_connected":    _get_engine() is not None,
        "in_memory_farms": list(set(list(_mem_env.keys()) + list(_mem_cost.keys()))),
    }
