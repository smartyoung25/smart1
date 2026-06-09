# -*- coding: utf-8 -*-
"""경량 자체 호스팅 텔레메트리 — 클라이언트 JS 에러·이벤트 수집(Sentry 대체).

외부 계정 없이 클라이언트 런타임 에러를 서버 로그로 적재해 운영 관측성 확보.
POST /api/telemetry/client : {type, message, url, ua, ts, extra} → data/telemetry/YYYY-MM-DD.jsonl
GET  /api/telemetry/summary : 최근 에러 집계(유형·화면별 카운트)
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Body

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

_DIR = Path(__file__).resolve().parents[1] / "data" / "telemetry"
_MAX_MSG = 500


def _path() -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{datetime.now(timezone.utc).isoformat()[:10]}.jsonl"


@router.post("/client", summary="클라이언트 런타임 에러·이벤트 수집")
def post_client(body: dict = Body(...)):
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": str(body.get("type", "error"))[:32],
        "message": str(body.get("message", ""))[:_MAX_MSG],
        "url": str(body.get("url", ""))[:300],
        "ua": str(body.get("ua", ""))[:200],
        "extra": body.get("extra") if isinstance(body.get("extra"), (dict, list)) else None,
    }
    try:
        with _path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"ok": True}


@router.get("/summary", summary="최근 텔레메트리 집계(유형·화면별)")
def get_summary(days: int = 7):
    from datetime import timedelta
    by_type, by_screen, total = {}, {}, 0
    recent = []
    today = datetime.now(timezone.utc).date()
    for d in range(days):
        fp = _DIR / f"{(today - timedelta(days=d)).isoformat()}.jsonl"
        if not fp.exists():
            continue
        try:
            for ln in fp.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln); total += 1
                by_type[r.get("type", "?")] = by_type.get(r.get("type", "?"), 0) + 1
                scr = (r.get("url", "").rsplit("/", 1)[-1] or "?").split("?")[0]
                by_screen[scr] = by_screen.get(scr, 0) + 1
                if len(recent) < 30:
                    recent.append({"ts": r.get("ts"), "type": r.get("type"),
                                   "message": (r.get("message") or "")[:120], "screen": scr})
        except Exception:
            continue
    return {"total": total, "by_type": by_type,
            "by_screen": dict(sorted(by_screen.items(), key=lambda x: -x[1])[:15]),
            "recent": recent, "days": days}
