"""인증 라우터 — JWT 토큰 발급 / 회원가입 / 온보딩.

POST /api/v1/auth/token              JWT 액세스 토큰 발급
POST /api/v1/auth/register           신규 회원가입
POST /api/v1/auth/onboarding         농장 프로필 온보딩 저장
GET  /api/v1/auth/onboarding/status  온보딩 완료 여부 조회
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# farm_registry.json 경로 (프로젝트 루트 기준)
_FARM_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "farm_registry.json"


# ── 스키마 ────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tier: str = "basic"
    chat_quota_max: int = 0
    onboarding_required: bool = False   # 최초 로그인 온보딩 필요 여부


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=4, max_length=64)
    name: str = Field("", max_length=64)
    email: str = Field("", max_length=128)


class OnboardingRequest(BaseModel):
    farm_id: str = ""
    crop_ko: str = ""
    facility_type: str = ""
    area_m2: Optional[float] = None
    cultivation_method: str = "토경"
    region: str = ""
    season_start: str = ""
    season_end: str = ""
    growing_year: int = 1
    pain_points: List[str] = []
    kpi_yield_kg: Optional[float] = None
    kpi_revenue_wan: Optional[float] = None
    kpi_energy_save: Optional[float] = None
    kpi_drain_rate: Optional[float] = None


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _verify_password(plain: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ImportError:
        logger.warning("[auth] bcrypt 미설치 — 평문 비교 사용 (개발 전용)")
        return plain == hashed


def _hash_password(plain: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        return plain   # 개발 전용 평문 폴백


def _build_token_response(user: dict, onboarding_required: bool = False) -> TokenResponse:
    """user dict → TokenResponse 조립 헬퍼."""
    from api.middleware.auth import create_access_token
    from api.services.billing import get_farm_tier, _AI_QUOTAS

    expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    role    = user.get("role", "farmer")
    farm_id = user.get("farm_id") or ""

    if role in ("admin", "manager"):
        tier = get_farm_tier(farm_id) if farm_id else "admin"
    else:
        tier = get_farm_tier(farm_id) if farm_id else "basic"

    chat_quota_max = _AI_QUOTAS.get(tier, 0)

    token = create_access_token({
        "sub":     user["username"],
        "role":    role,
        "farm_id": farm_id,
        "tier":    tier,
        "user_id": user.get("id", 0),
    })
    return TokenResponse(
        access_token=token,
        expires_in=expire_minutes * 60,
        tier=tier,
        chat_quota_max=chat_quota_max,
        onboarding_required=onboarding_required,
    )


# ── 농장 자동 등록 헬퍼 ───────────────────────────────────────────────────────

def _register_farm_from_onboarding(farm_id: str, req: "OnboardingRequest") -> None:
    """온보딩 데이터로 신규 농장을 _FARM_META 및 farm_registry.json에 등록한다.

    - 이미 등록된 farm_id는 덮어쓰지 않는다 (중복 안전).
    - JSON 파일 갱신 실패 시에도 in-memory 등록은 성공으로 처리한다.
    """
    # 1) in-memory _FARM_META에 동적 등록
    try:
        from api.routers.farmer import _FARM_META
        from engine.farm_tier import FarmTier

        if farm_id not in _FARM_META:
            crop = req.crop_ko or "미상"
            # region 예: "경북 성주" / "충남 논산" / "전북 익산" …
            region_parts = (req.region or "").split()
            sido     = region_parts[0] if len(region_parts) > 0 else None
            sigungu  = region_parts[1] if len(region_parts) > 1 else None

            _FARM_META[farm_id] = {
                "tier":           FarmTier.MANUAL,
                "area_m2":        float(req.area_m2) if req.area_m2 else 1000.0,
                "iot_available":  False,
                "name":           f"{crop} 농장 ({farm_id})",
                "crop":           crop,
                "sido":           sido,
                "sigungu":        sigungu,
                "address_detail": "",
            }
            logger.info("[auth] _FARM_META 동적 등록: %s (작목=%s)", farm_id, crop)
    except Exception as e:
        logger.warning("[auth] _FARM_META 동적 등록 실패: %s", e)

    # 2) farm_registry.json 갱신 (영속화)
    try:
        registry: dict = {}
        if _FARM_REGISTRY_PATH.exists():
            with open(_FARM_REGISTRY_PATH, encoding="utf-8") as f:
                registry = json.load(f)

        farms = registry.setdefault("farms", {})
        if farm_id not in farms:
            crop = req.crop_ko or "미상"
            region_parts = (req.region or "").split()
            sido    = region_parts[0] if len(region_parts) > 0 else "—"
            sigungu = region_parts[1] if len(region_parts) > 1 else "—"

            farms[farm_id] = {
                "crop":           crop,
                "crop_ko":        crop,
                "sido":           sido,
                "sigungu":        sigungu,
                "area_m2":        float(req.area_m2) if req.area_m2 else 1000.0,
                "name":           f"{crop} 농장 ({farm_id})",
                "iot_available":  False,
                "onboarding":     True,
            }
            registry["total_farms"] = len(farms)

            with open(_FARM_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
            logger.info("[auth] farm_registry.json 갱신 완료: %s", farm_id)
    except Exception as e:
        logger.warning("[auth] farm_registry.json 갱신 실패 (무시): %s", e)


# ── 로그인 (토큰 발급) ────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse, summary="JWT 액세스 토큰 발급")
async def issue_token(req: TokenRequest):
    """사용자명/패스워드 검증 후 JWT 토큰 반환."""
    from api.services.persistence import get_user_by_username

    user = get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 실패")
    if not _verify_password(req.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 실패")

    # farmer/viewer는 farm_id 기본값 보정
    role = user.get("role", "viewer")
    if role not in ("admin", "manager") and not user.get("farm_id"):
        user["farm_id"] = "farm_001"

    # admin/manager는 온보딩 불필요
    if role in ("admin", "manager"):
        onboarding_required = False
    else:
        onboarding_required = not bool(user.get("onboarding_completed", False))
    return _build_token_response(user, onboarding_required=onboarding_required)


# ── 회원가입 ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, summary="신규 회원가입")
async def register(req: RegisterRequest):
    """사용자명·패스워드·이름·이메일 검증 후 계정 생성 및 JWT 반환."""
    from api.services.persistence import create_user

    try:
        user = create_user(
            username=req.username,
            hashed_password=_hash_password(req.password),
            name=req.name,
            email=req.email,
            role="farmer",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error("[auth] register 오류: %s", e)
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다.")

    return _build_token_response(user, onboarding_required=True)


# ── 온보딩 저장 ───────────────────────────────────────────────────────────────

@router.post("/onboarding", summary="농장 프로필 온보딩 저장")
async def save_onboarding(
    req: OnboardingRequest,
    token_user: dict = Depends(__import__("api.middleware.auth", fromlist=["require_auth"]).require_auth),
):
    """온보딩 5단계 데이터 저장. JWT 인증 필요."""
    from api.services.persistence import save_onboarding as _save

    user_id = token_user.get("user_id") or 0
    farm_id = req.farm_id or token_user.get("farm_id") or ""

    if not user_id:
        raise HTTPException(status_code=400, detail="user_id를 JWT에서 확인할 수 없습니다.")

    try:
        _save(user_id=int(user_id), farm_id=farm_id, data=req.model_dump())
    except Exception as e:
        logger.error("[auth] save_onboarding 오류: %s", e)
        raise HTTPException(status_code=500, detail="온보딩 저장 중 오류가 발생했습니다.")

    # ── farm_registry.json 및 _FARM_META에 신규 농장 자동 등록 ─────────────────
    if farm_id:
        try:
            _register_farm_from_onboarding(farm_id, req)
        except Exception as _fe:
            logger.warning("[auth] 농장 자동 등록 실패(무시): %s", _fe)

    return {"status": "ok", "farm_id": farm_id, "message": "온보딩 데이터가 저장됐습니다."}


# ── 온보딩 상태 조회 ──────────────────────────────────────────────────────────

@router.get("/onboarding/status", summary="온보딩 완료 여부 조회")
async def get_onboarding_status(
    token_user: dict = Depends(__import__("api.middleware.auth", fromlist=["require_auth"]).require_auth),
):
    """현재 사용자의 온보딩 완료 여부와 기존 데이터 반환."""
    from api.services.persistence import get_user_by_username, get_onboarding

    user = get_user_by_username(token_user.get("sub", ""))
    if not user:
        raise HTTPException(status_code=404, detail="사용자 정보를 찾을 수 없습니다.")

    user_id  = user.get("id", 0)
    completed = bool(user.get("onboarding_completed", False))
    onboarding_data = get_onboarding(int(user_id)) if user_id else None

    return {
        "completed": completed,
        "user_id":   user_id,
        "data":      onboarding_data,
    }
