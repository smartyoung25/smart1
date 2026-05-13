"""Smart Farm API — FastAPI application entry point."""
from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from api.routers import farmer, admin
from api.routers.auth import router as auth_router
from api.middleware.auth import JWTMiddleware

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(
    title="Smart Farm AI Platform",
    version="0.2.0",
    description="양방향 스마트팜 대시보드 API",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS (환경변수 기반 허용 출처) ─────────────────────────────────────────────
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── JWT 미들웨어 (JWT_SECRET_KEY 없으면 자동 비활성화) ────────────────────────
app.add_middleware(JWTMiddleware)

# ── 라우터 등록 ───────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(farmer.router)
app.include_router(admin.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "version": app.version}
