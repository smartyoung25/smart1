"""스마트팜 AI 플랫폼 — 빌링/티어 서비스.

티어 우선순위: DB(subscriptions) > api/data/subscriptions.json > 기본값 'basic'
AI 쿼터:     DB(usage_logs) > api/data/quota_cache.json > 0

빠른 시작:
    from api.services.billing import get_farm_tier, check_feature, check_chat_quota, consume_chat_quota
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
_ROOT        = Path(__file__).resolve().parents[2]
_FEATURES_F  = _ROOT / "api" / "data" / "tier_features.json"
_SUBS_F      = _ROOT / "api" / "data" / "subscriptions.json"    # 폴백 JSON
_QUOTA_F     = _ROOT / "api" / "data" / "quota_cache.json"      # 쿼터 폴백

_lock = Lock()

# ── tier_features.json 로드 ────────────────────────────────────────────────────
def _load_features() -> dict:
    try:
        return json.loads(_FEATURES_F.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("[billing] tier_features.json 로드 실패: %s", exc)
        return {"tiers": {}, "features": {}, "ai_quotas": {}}

_FEATURES: dict = _load_features()
_TIER_RANK: dict[str, int] = {
    t: v["rank"] for t, v in _FEATURES.get("tiers", {}).items()
}
_AI_QUOTAS: dict[str, int] = _FEATURES.get("ai_quotas", {
    "basic": 0, "smart": 30, "pro": 200, "enterprise": -1,
})

# ── 폴백 JSON 구독 테이블 ─────────────────────────────────────────────────────
def _load_subs_json() -> dict[str, str]:
    """subscriptions.json {farm_id: tier} 딕셔너리 반환."""
    try:
        if _SUBS_F.exists():
            return json.loads(_SUBS_F.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[billing] subscriptions.json 로드 실패: %s", exc)
    # 기본 설정 (demo)
    return {
        "farm_001": "pro",
        "farm_002": "smart",
        "farm_003": "smart",
        "farm_004": "basic",
        "farm_005": "basic",
    }

def _save_subs_json(subs: dict[str, str]) -> None:
    try:
        _SUBS_F.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("[billing] subscriptions.json 저장 실패: %s", exc)


# ── DB 조회 (postgresql 연결이 있으면 사용) ───────────────────────────────────
def _db_get_tier(farm_id: str) -> Optional[str]:
    try:
        from api.services.db import get_connection   # type: ignore
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tier FROM subscriptions WHERE farm_id = %s AND status = 'active'",
                    (farm_id,)
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def _db_get_chat_usage(farm_id: str) -> int:
    """이번 달 AI 채팅 사용 횟수를 DB에서 조회."""
    try:
        from api.services.db import get_connection   # type: ignore
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COALESCE(SUM(quota_consumed), 0)
                       FROM usage_logs
                       WHERE farm_id = %s
                         AND feature_code = 'ai_chat_basic'
                         AND ts >= DATE_TRUNC('month', NOW())""",
                    (farm_id,)
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
    except Exception:
        return -1   # -1 = DB 조회 실패 → JSON 폴백


def _db_log_usage(farm_id: str, feature_code: str, endpoint: str = "") -> None:
    try:
        from api.services.db import get_connection   # type: ignore
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO usage_logs (farm_id, feature_code, endpoint) VALUES (%s, %s, %s)",
                    (farm_id, feature_code, endpoint)
                )
            conn.commit()
    except Exception:
        pass   # 로깅 실패는 무시


# ── 쿼터 폴백 JSON ────────────────────────────────────────────────────────────
def _load_quota_json() -> dict:
    """{ "farm_001": { "2026-05": 12 } }"""
    try:
        if _QUOTA_F.exists():
            return json.loads(_QUOTA_F.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_quota_json(data: dict) -> None:
    try:
        _QUOTA_F.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[billing] quota_cache.json 저장 실패: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def get_farm_tier(farm_id: str) -> str:
    """농장의 현재 구독 티어 반환. DB 우선 → JSON 폴백 → 'basic'."""
    tier = _db_get_tier(farm_id)
    if tier:
        return tier
    subs = _load_subs_json()
    return subs.get(farm_id, "basic")


def set_farm_tier(farm_id: str, tier: str) -> None:
    """농장 티어 변경 (JSON 저장). DB 있으면 DB도 업데이트."""
    if tier not in _TIER_RANK:
        raise ValueError(f"유효하지 않은 티어: {tier}")
    with _lock:
        subs = _load_subs_json()
        subs[farm_id] = tier
        _save_subs_json(subs)
    # DB 업데이트 시도
    try:
        from api.services.db import get_connection   # type: ignore
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO subscriptions (farm_id, tier, status)
                       VALUES (%s, %s, 'active')
                       ON CONFLICT (farm_id) DO UPDATE SET tier = %s, updated_at = NOW()""",
                    (farm_id, tier, tier)
                )
            conn.commit()
    except Exception:
        pass


def tier_rank(tier: str) -> int:
    """티어 → 순위 숫자 (basic=1, smart=2, pro=3, enterprise=4)."""
    return _TIER_RANK.get(tier, 0)


def check_feature(farm_id: str, feature_code: str) -> dict:
    """기능 접근 가능 여부 반환.

    Returns:
        {
          "allowed": bool,
          "current_tier": str,
          "min_tier": str,
          "upgrade_to": str | None,   # 필요한 최소 티어
          "label_ko": str,
        }
    """
    features = _FEATURES.get("features", {})
    feat_def  = features.get(feature_code, {})
    min_tier  = feat_def.get("min_tier", "basic")
    label_ko  = feat_def.get("label_ko", feature_code)

    current   = get_farm_tier(farm_id)
    allowed   = tier_rank(current) >= tier_rank(min_tier)

    return {
        "allowed":      allowed,
        "current_tier": current,
        "min_tier":     min_tier,
        "upgrade_to":   None if allowed else min_tier,
        "label_ko":     label_ko,
        "section":      feat_def.get("section", ""),
    }


def check_chat_quota(farm_id: str) -> dict:
    """AI 채팅 쿼터 확인.

    Returns:
        {
          "allowed":   bool,
          "used":      int,
          "max":       int,   # -1 = 무제한
          "remaining": int,   # -1 = 무제한
          "tier":      str,
        }
    """
    tier = get_farm_tier(farm_id)
    max_quota = _AI_QUOTAS.get(tier, 0)

    if max_quota == 0:
        return {"allowed": False, "used": 0, "max": 0, "remaining": 0, "tier": tier}

    if max_quota == -1:
        return {"allowed": True, "used": 0, "max": -1, "remaining": -1, "tier": tier}

    # 사용량 조회
    used = _db_get_chat_usage(farm_id)
    if used < 0:   # DB 실패 → JSON 폴백
        month_key = datetime.now(tz=timezone.utc).strftime("%Y-%m")
        with _lock:
            quota_data = _load_quota_json()
        used = quota_data.get(farm_id, {}).get(month_key, 0)

    remaining = max(0, max_quota - used)
    return {
        "allowed":   used < max_quota,
        "used":      used,
        "max":       max_quota,
        "remaining": remaining,
        "tier":      tier,
    }


def consume_chat_quota(farm_id: str) -> bool:
    """AI 채팅 1회 사용 처리. 성공=True, 쿼터 초과=False."""
    quota = check_chat_quota(farm_id)
    if not quota["allowed"]:
        return False

    # DB 로깅
    _db_log_usage(farm_id, "ai_chat_basic", "/chat")

    # JSON 폴백 카운터 증가
    month_key = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    with _lock:
        quota_data = _load_quota_json()
        farm_quota = quota_data.get(farm_id, {})
        farm_quota[month_key] = farm_quota.get(month_key, 0) + 1
        quota_data[farm_id] = farm_quota
        _save_quota_json(quota_data)

    return True


def get_plan_info(farm_id: str) -> dict:
    """농장의 현재 플랜 전체 정보 반환 (GET /billing/plan 응답용)."""
    tier = get_farm_tier(farm_id)
    tier_meta = _FEATURES.get("tiers", {}).get(tier, {})
    features = _FEATURES.get("features", {})
    chat_quota = check_chat_quota(farm_id)

    # 섹션별 가용 기능 목록
    unlocked: list[dict] = []
    locked:   list[dict] = []
    for code, feat in features.items():
        min_t = feat.get("min_tier", "basic")
        entry = {
            "feature_code": code,
            "label_ko":     feat.get("label_ko", code),
            "section":      feat.get("section", ""),
            "min_tier":     min_t,
        }
        if tier_rank(tier) >= tier_rank(min_t):
            unlocked.append(entry)
        else:
            locked.append(entry)

    return {
        "farm_id":         farm_id,
        "tier":            tier,
        "tier_name_ko":    tier_meta.get("name_ko", tier),
        "price_krw_month": tier_meta.get("price_krw_month", 0),
        "color":           tier_meta.get("color", "#8892a4"),
        "chat_quota":      chat_quota,
        "unlocked_count":  len(unlocked),
        "locked_count":    len(locked),
        "unlocked":        unlocked,
        "locked":          locked,
        "upgrade_options": _upgrade_options(tier),
    }


def _upgrade_options(current_tier: str) -> list[dict]:
    """현재 티어에서 업그레이드 가능한 상위 티어 목록."""
    opts = []
    tiers = _FEATURES.get("tiers", {})
    cur_rank = tier_rank(current_tier)
    for t, meta in sorted(tiers.items(), key=lambda x: x[1]["rank"]):
        if meta["rank"] > cur_rank:
            opts.append({
                "tier":            t,
                "name_ko":         meta["name_ko"],
                "price_krw_month": meta["price_krw_month"],
                "color":           meta.get("color", "#8892a4"),
            })
    return opts
