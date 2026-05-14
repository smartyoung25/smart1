"""인증 라우터 — JWT 토큰 발급.

POST /api/v1/auth/token
    Body: {username, password}
    Returns: {access_token, token_type}
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        import bcrypt
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ImportError:
        # fallback: plain text compare (개발 전용, 절대 운영 사용 금지)
        logger.warning("[auth] bcrypt 미설치 — 평문 비교 사용 (개발 전용)")
        return plain == hashed


@router.post("/token", response_model=TokenResponse, summary="JWT 액세스 토큰 발급")
async def issue_token(req: TokenRequest):
    """사용자명/패스워드 검증 후 JWT 토큰 반환."""
    from api.services.persistence import get_user_by_username
    from api.middleware.auth import create_access_token

    user = get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 실패")

    if not _verify_password(req.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 실패")

    expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    token = create_access_token(
        {"sub": user["username"], "role": user.get("role", "viewer")}
    )
    return TokenResponse(access_token=token, expires_in=expire_minutes * 60)
