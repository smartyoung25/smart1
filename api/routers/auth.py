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

import re as _re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 국내 휴대폰/일반전화: 숫자·하이픈 허용, 숫자 9~11자리
_PHONE_RE = _re.compile(r"^0\d{1,2}-?\d{3,4}-?\d{4}$")

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# 공개 데모 모드 — 무자격 데모토큰 발급 게이트
_PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").lower() in ("1", "true", "yes")

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
    email: str = Field(..., min_length=5, max_length=128)   # 필수
    phone: str = Field(..., min_length=9, max_length=20)    # 필수 (연락처)
    role: str = Field("farmer", max_length=20)              # farmer|org|distributor|expert|public

    @field_validator("role")
    @classmethod
    def _chk_role(cls, v: str) -> str:
        v = (v or "farmer").strip()
        return v if v in ("farmer", "org", "distributor", "expert", "public") else "farmer"

    @field_validator("email")
    @classmethod
    def _chk_email(cls, v: str) -> str:
        v = (v or "").strip()
        if not _EMAIL_RE.match(v):
            raise ValueError("올바른 이메일 형식이 아닙니다.")
        return v

    @field_validator("phone")
    @classmethod
    def _chk_phone(cls, v: str) -> str:
        v = (v or "").strip()
        if not _PHONE_RE.match(v):
            raise ValueError("올바른 전화번호 형식이 아닙니다. (예: 010-1234-5678)")
        return v


class PasswordForgotRequest(BaseModel):
    # 아이디 또는 이메일 중 하나로 식별
    username: str = Field("", max_length=64)
    email: str = Field("", max_length=128)


class PasswordResetRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=128)
    new_password: str = Field(..., min_length=4, max_length=64)


class OnboardingRequest(BaseModel):
    farm_id: str = ""
    farm_name: str = ""                       # 사람이 읽는 농장명(표시용)
    crop_ko: str = ""
    facility_type: str = ""
    area_m2: Optional[float] = None
    cultivation_method: str = "토경"
    cultivation_detail: str = ""              # 양액 세부(담액/NFT/암면/코코 등)
    irrigation_method: str = ""               # 노지 관개방식(이전엔 저장 누락)
    region: str = ""
    sido: str = ""
    sigungu: str = ""
    emd: str = ""                             # 읍면동
    address_detail: str = ""
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
        # 평문 폴백 제거 — 무음 보안 취약점 차단
        raise RuntimeError(
            "[auth] bcrypt 미설치. 서버를 종료하고 "
            "`pip install bcrypt>=4.1.0` 실행 후 재시작하세요. "
            "(requirements.api.txt 에 이미 명시됨)"
        )


def _hash_password(plain: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    except ImportError:
        raise RuntimeError(
            "[auth] bcrypt 미설치 — 회원가입 불가. "
            "`pip install bcrypt>=4.1.0` 실행 후 재시작하세요."
        )


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
            # 구조화 지역 우선, 없으면 region 문자열 split 폴백
            _rp = (req.region or "").split()
            sido     = req.sido or (_rp[0] if len(_rp) > 0 else None)
            sigungu  = req.sigungu or (_rp[1] if len(_rp) > 1 else None)

            _fac = req.facility_type or ""
            _cm  = req.cultivation_method or ""
            _is_field = ("노지" in _fac) or ("비가림" in _fac) or ("노지" in _cm)
            _FARM_META[farm_id] = {
                "tier":           FarmTier.MANUAL,
                "area_m2":        float(req.area_m2) if req.area_m2 else 1000.0,
                "iot_available":  False,
                "name":           (req.farm_name or f"{crop} 농장 ({farm_id})"),
                "crop":           crop,
                "sido":           sido,
                "sigungu":        sigungu,
                "emd":            req.emd or "",
                "address_detail": req.address_detail or "",
                "facility_type":  _fac,
                "cultivation_method": _cm,
                "cultivation_detail": req.cultivation_detail or "",
                "irrigation_method":  req.irrigation_method or "",
                "farm_type":      "field" if _is_field else "greenhouse",
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
            _rp = (req.region or "").split()
            sido    = req.sido or (_rp[0] if len(_rp) > 0 else "—")
            sigungu = req.sigungu or (_rp[1] if len(_rp) > 1 else "—")

            farms[farm_id] = {
                "crop":           crop,
                "crop_ko":        crop,
                "sido":           sido,
                "sigungu":        sigungu,
                "emd":            req.emd or "",
                "area_m2":        float(req.area_m2) if req.area_m2 else 1000.0,
                "name":           (req.farm_name or f"{crop} 농장 ({farm_id})"),
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

    # Z3 차단: farm_id 없는 일반 사용자를 실증농장 farm_001로 자동 보정하지 않는다.
    #   (신규 가입자는 create_user가 고유 farm_id를 부여하므로 빈 값이 정상적으로 없음.
    #    혹시 빈 값이면 그대로 둬 farmer 소유권 검증(Z1)이 거부하도록 한다.)
    role = user.get("role", "viewer")

    # admin/manager는 온보딩 불필요
    if role in ("admin", "manager"):
        onboarding_required = False
    else:
        onboarding_required = not bool(user.get("onboarding_completed", False))
    return _build_token_response(user, onboarding_required=onboarding_required)


@router.post("/demo-token", response_model=TokenResponse, summary="공개 데모 토큰 발급(무자격)")
async def issue_demo_token():
    """공개 데모(PUBLIC_DEMO=1) 전용 — 자격증명 없이 데모 토큰 발급.

    클라이언트 소스에 admin/비밀번호를 박지 않기 위한 근본 대책:
      - role="demo" (관리자 아님), farm_id="farm_001"
      - 전 기능 시연을 위해 tier="enterprise"로 노출
      - 파괴적·관리자 쓰기는 PublicDemoMiddleware가 차단,
        admin 조회화면은 require_admin_view가 demo 역할의 GET만 허용.
    PUBLIC_DEMO가 아니면 발급하지 않는다(403).
    """
    if not _PUBLIC_DEMO:
        raise HTTPException(status_code=403, detail="데모 토큰은 공개 데모 모드에서만 발급됩니다.")
    from api.middleware.auth import create_access_token
    from api.services.billing import _AI_QUOTAS

    expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    tier = "enterprise"
    token = create_access_token({
        "sub":     "demo",
        "role":    "demo",
        "farm_id": "farm_001",
        "tier":    tier,
        "user_id": 0,
        "demo":    True,
    })
    return TokenResponse(
        access_token=token,
        expires_in=expire_minutes * 60,
        tier=tier,
        chat_quota_max=_AI_QUOTAS.get(tier, 0),
        onboarding_required=False,
    )


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
            phone=req.phone,
            role=req.role,   # C0 선택 역할 저장(farmer|org|distributor|expert|public)
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error("[auth] register 오류: %s", e)
        raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다.")

    return _build_token_response(user, onboarding_required=True)


# ── 비밀번호 찾기 / 재설정 (이메일 연동) ──────────────────────────────────────────

import secrets as _secrets
import time as _time

_RESET_PATH = Path(__file__).parent.parent / "data" / "password_resets.json"
_RESET_TTL = 1800   # 30분


def _load_resets() -> dict:
    try:
        if _RESET_PATH.exists():
            return json.loads(_RESET_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_resets(d: dict) -> None:
    try:
        _RESET_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("[auth] 재설정 토큰 저장 실패: %s", e)


@router.post("/password/forgot", summary="비밀번호 재설정 요청 (이메일 발송)")
async def password_forgot(req: PasswordForgotRequest):
    """아이디 또는 이메일로 사용자를 찾아 재설정 링크를 이메일로 발송.
    사용자 열거 방지를 위해 응답 메시지는 항상 동일하다."""
    from api.services.persistence import get_user_by_username, get_user_by_email
    from api.services import mailer

    user = None
    if req.username:
        user = get_user_by_username(req.username)
    if not user and req.email:
        user = get_user_by_email(req.email)

    generic = {"detail": "가입된 계정이라면 등록된 이메일로 재설정 안내를 보냈습니다."}
    if not user:
        return generic

    token = _secrets.token_urlsafe(24)
    store = _load_resets()
    # 만료 토큰 청소
    now = int(_time.time())
    store = {k: v for k, v in store.items() if v.get("exp", 0) > now}
    store[token] = {"username": user["username"], "exp": now + _RESET_TTL}
    _save_resets(store)

    email = user.get("email") or req.email
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    link = f"{base}/screens/c0_reset.html?token={token}"
    ok, _msg = mailer.send_email(
        email, "[KAASA smartfarmingsight] 비밀번호 재설정",
        f"안녕하세요.\n\n아래 링크에서 새 비밀번호를 설정하세요. (30분간 유효)\n{link}\n\n"
        f"본인이 요청하지 않았다면 이 메일을 무시하세요.",
    )

    resp = dict(generic)
    if not ok:
        # 이메일 서버 미설정(데모) — 정직하게 재설정 링크를 직접 반환
        resp["demo_reset_link"] = link
        resp["note"] = "이메일 서버 미설정(데모): 위 링크로 직접 재설정하세요. (운영 시 SMTP_* 환경변수 주입하면 자동 메일 발송)"
    return resp


@router.post("/password/reset", summary="새 비밀번호 설정 (토큰 검증)")
async def password_reset(req: PasswordResetRequest):
    from api.services.persistence import set_user_password

    store = _load_resets()
    entry = store.get(req.token)
    if not entry or entry.get("exp", 0) < int(_time.time()):
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 링크입니다. 다시 요청하세요.")

    if not set_user_password(entry["username"], _hash_password(req.new_password)):
        raise HTTPException(status_code=500, detail="비밀번호 변경에 실패했습니다.")

    store.pop(req.token, None)
    _save_resets(store)
    return {"detail": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인하세요."}


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
