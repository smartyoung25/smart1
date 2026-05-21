"""AI 채팅 서비스 — Claude API 연동.

티어별 모델 선택:
    basic  → 허용 안 됨 (billing 레이어에서 차단)
    smart  → 규칙 기반 stub (_stub_reply 위임)
    pro    → claude-3-haiku-20240307  (빠름·저비용)
    enterprise → claude-3-5-sonnet-20241022 (고성능)

환경변수:
    ANTHROPIC_API_KEY   : 필수 (없으면 전 티어 stub 폴백)
    AI_CHAT_MAX_TOKENS  : 응답 최대 토큰 (기본 800)
    AI_CHAT_TIMEOUT     : API 타임아웃 초 (기본 20)

반환 형식:
    {
        "reply":           str,
        "suggestions":     list[str],    # 후속 질문 3개
        "model_used":      str,
        "referenced_data": list[str],
        "tokens_used":     int,
    }
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 티어 → Claude 모델 (변경 없음)
_TIER_MODEL: dict[str, str] = {
    "pro":        "claude-haiku-4-5",
    "enterprise": "claude-sonnet-4-5",
}


def _cfg(key: str, default: str = "") -> str:
    """.env → 환경변수 순서로 값을 읽는다.

    main.py가 load_dotenv()를 호출하지만, 모듈 캐시 타이밍 문제를
    피하기 위해 호출 시점마다 os.environ을 직접 조회한다.
    ANTHROPIC_API_KEY 가 비어 있으면 .env 파일을 직접 파싱해 반환한다.
    """
    val = os.environ.get(key, "").strip()
    if val:
        return val
    # .env 직접 파싱 (fallback — FastAPI 외부 단독 실행 대비)
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
        except Exception:
            pass
    return default

# 티어 → Claude 모델
_TIER_MODEL: dict[str, str] = {
    "pro":        "claude-haiku-4-5",
    "enterprise": "claude-sonnet-4-5",
}


# ── 시스템 프롬프트 빌더 ──────────────────────────────────────────────────────

def _build_system_prompt(ctx: dict) -> str:
    crop   = ctx.get("crop",       "작물")
    area   = ctx.get("area_m2",    0)
    name   = ctx.get("farm_name",  ctx.get("farm_id", ""))
    loc    = ctx.get("location",   "국내")
    today  = date.today().isoformat()

    # 환경 요약
    env = ctx.get("env", {})
    env_lines = []
    _env_map = [
        ("temp_internal", "내부온도",   "°C"),
        ("humidity_int",  "내부습도",   "%"),
        ("co2_ppm",       "CO₂",        "ppm"),
        ("solar_rad",     "일사량",     "W/m²"),
        ("ec_dsm",        "EC",         "dS/m"),
        ("soil_temp",     "지온",       "°C"),
    ]
    for key, label, unit in _env_map:
        val = env.get(key)
        if val is not None:
            env_lines.append(f"  {label}: {val}{unit}")

    env_section = "\n".join(env_lines) if env_lines else "  (데이터 없음)"

    # 알림 요약
    alerts = ctx.get("alerts", [])
    alert_section = (
        "\n".join(f"  [{a.get('severity','').upper()}] {a.get('message_ko','')}"
                  for a in alerts[:5])
        if alerts else "  없음"
    )

    # 핵심 경영 지표
    price  = ctx.get("price_krw_kg", 0)
    yield_ = ctx.get("yield_kg_m2",  0)
    cost   = ctx.get("cost_per_m2",  0)
    profit = round((yield_ * price - cost) * area / 10_000) if area else 0

    return f"""당신은 한국 스마트팜 전문 AI 컨설턴트입니다.

[농장 정보]
이름: {name} | 작목: {crop} | 면적: {area}m² | 위치: {loc} | 날짜: {today}

[현재 환경]
{env_section}

[활성 알림 ({len(alerts)}건)]
{alert_section}

[경영 지표]
  KAMIS 단가: {price:,.0f}원/kg
  예상 수확량: {yield_}kg/m²
  운영비: {cost:,.0f}원/m²
  예상 월 순이익: {profit:,}만원

[지시사항]
- 반드시 한국어로 답변하세요.
- 위 실데이터를 구체적으로 인용하세요. 수치 없는 일반론 금지.
- 답변 마지막에 농가가 이어서 질문할 법한 후속 질문 3개를 제안하세요.
- 응답은 반드시 아래 JSON 형식으로만 출력하세요 (마크다운 코드블록 없이):
{{"reply": "본문 답변 (마크다운 허용)", "suggestions": ["후속질문1", "후속질문2", "후속질문3"]}}"""


# ── Claude API 호출 ───────────────────────────────────────────────────────────

def call_claude(
    farm_id: str,
    message: str,
    history: list[dict],   # [{"role":"user","content":"..."}, ...]
    context: dict,
    tier: str = "pro",
) -> dict:
    """Claude API 동기 호출.

    Returns:
        {"reply": str, "suggestions": list[str], "model_used": str,
         "referenced_data": list[str], "tokens_used": int}
    """
    model      = _TIER_MODEL.get(tier, _TIER_MODEL["pro"])
    api_key    = _cfg("ANTHROPIC_API_KEY")
    max_tokens = int(_cfg("AI_CHAT_MAX_TOKENS", "800"))
    timeout    = float(_cfg("AI_CHAT_TIMEOUT", "20"))

    if not api_key:
        logger.warning("[ai_chat] ANTHROPIC_API_KEY 미설정 — stub 폴백")
        return _error_fallback("ANTHROPIC_API_KEY가 .env에 설정되지 않았습니다.")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    except Exception as e:
        logger.error("[ai_chat] Anthropic 클라이언트 초기화 실패: %s", e)
        return _error_fallback(str(e))

    system_prompt = _build_system_prompt(context)

    # 히스토리 최대 10턴 (비용 제어)
    msgs = history[-10:]
    msgs.append({"role": "user", "content": message})

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=msgs,
        )
        raw_text   = resp.content[0].text.strip()
        tokens_in  = resp.usage.input_tokens
        tokens_out = resp.usage.output_tokens
        logger.info(
            "[ai_chat] farm=%s tier=%s model=%s tokens=%d+%d",
            farm_id, tier, model, tokens_in, tokens_out,
        )
    except anthropic.APIStatusError as e:
        logger.error("[ai_chat] API 오류 %s: %s", e.status_code, e.message)
        return _error_fallback(f"API 오류 {e.status_code}")
    except anthropic.APITimeoutError:
        logger.warning("[ai_chat] 타임아웃 farm=%s", farm_id)
        return _error_fallback("응답 시간 초과 — 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        logger.error("[ai_chat] 예외 farm=%s: %s", farm_id, e)
        return _error_fallback(str(e))

    # JSON 파싱
    parsed = _parse_response(raw_text)
    parsed["model_used"]      = model
    parsed["tokens_used"]     = tokens_in + tokens_out
    parsed["referenced_data"] = _infer_referenced(message)
    return parsed


def _parse_response(text: str) -> dict:
    """Claude 응답 JSON 파싱. 실패 시 전체를 reply로 처리."""
    # ```json ... ``` 블록 제거
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()

    try:
        data = json.loads(text)
        return {
            "reply":       str(data.get("reply", text)),
            "suggestions": list(data.get("suggestions", [])),
        }
    except json.JSONDecodeError:
        # JSON이 아닌 경우 — 본문을 reply로 그대로 사용
        # 후속 질문 추출 시도 ("1.", "2.", "3." 패턴)
        import re
        suggs = re.findall(r"(?:^|\n)\s*\d+[.)] (.+)", text)[:3]
        body  = re.sub(r"\n\s*\d+[.)] .+", "", text).strip()
        return {"reply": body or text, "suggestions": suggs}


def _infer_referenced(message: str) -> list[str]:
    """메시지 키워드에서 참조 데이터 태그 추론."""
    msg = message.lower()
    refs = []
    if any(k in msg for k in ["온도","습도","co2","환경","센서"]): refs.append("environment")
    if any(k in msg for k in ["수확","예측","d-","출하"]):          refs.append("harvest")
    if any(k in msg for k in ["수익","매출","가격","이익","단가"]): refs.append("revenue")
    if any(k in msg for k in ["병해","질병","곰팡이","역병"]):      refs.append("disease_risk")
    if any(k in msg for k in ["추천","제안","최적","개선"]):        refs.append("recommendations")
    if any(k in msg for k in ["관수","배액","함수율","ec"]):        refs.append("irrigation")
    return refs or ["general"]


def _error_fallback(detail: str) -> dict:
    return {
        "reply":           f"AI 응답을 가져오지 못했습니다: {detail}\n\n잠시 후 다시 시도하거나, 기본 상담 기능을 이용해 주세요.",
        "suggestions":     ["다시 시도하기", "현재 알림 확인", "수확 예측 보기"],
        "model_used":      "fallback",
        "tokens_used":     0,
        "referenced_data": [],
    }


# ── 컨텍스트 빌더 헬퍼 (farmer.py에서 호출) ──────────────────────────────────

def build_farm_context(
    farm_id: str,
    meta: dict,
    env: dict,
    alerts: list,
) -> dict:
    """Claude에 전달할 농장 컨텍스트 dict 생성."""
    crop  = meta.get("crop", "작물")
    area  = meta.get("area_m2", 0)

    # 가격·수확량·비용 (import 순환 방지 — 지연 import)
    try:
        from api.data.stats_loader import get_price_krw_kg, get_yield_kg_m2
        price  = get_price_krw_kg(crop)
        yield_ = get_yield_kg_m2(crop)
    except Exception:
        price = yield_ = 0.0

    cost_per_m2 = 0.0
    try:
        from api.routers.farmer import _compute_costs   # type: ignore
        cost_per_m2 = _compute_costs(farm_id).cost_per_m2
    except Exception:
        pass

    # 환경값 정규화 (dict-value vs scalar)
    env_norm = {}
    for k, v in env.items():
        env_norm[k] = v.get("value", v) if isinstance(v, dict) else v

    return {
        "farm_id":    farm_id,
        "farm_name":  meta.get("name", farm_id),
        "crop":       crop,
        "area_m2":    area,
        "location":   f"{meta.get('sido', '')} {meta.get('sigungu', '')}".strip() or "국내",
        "env":        env_norm,
        "alerts":     [{"severity": a.severity, "message_ko": a.message_ko} for a in alerts],
        "price_krw_kg": round(price, 0),
        "yield_kg_m2":  round(yield_, 3),
        "cost_per_m2":  round(cost_per_m2, 0),
    }
