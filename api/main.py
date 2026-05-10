"""Smart Farm API — FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import farmer, admin

app = FastAPI(
    title="Smart Farm AI Platform",
    version="0.1.0",
    description="양방향 스마트팜 대시보드 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(farmer.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok"}
