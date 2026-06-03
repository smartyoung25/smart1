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
    if any(k in msg for k in ["병해","질병","곰팡이","역병","습도","건조"]):  refs.append("disease_risk")
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


def call_ai(
    farm_id: str,
    message: str,
    history: list[dict],
    context: dict,
    tier: str = "pro",
) -> dict:
    """AI 채팅 멀티-프로바이더 폴백 체인.

    우선순위: Anthropic Claude → OpenAI GPT → 규칙 기반 stub
    """
    # ① Anthropic (기본)
    anthropic_key = _cfg("ANTHROPIC_API_KEY")
    if anthropic_key:
        result = call_claude(farm_id, message, history, context, tier)
        if result.get("model_used") != "fallback":
            return result

    # ② OpenAI (폴백 1)
    openai_key = _cfg("OPENAI_API_KEY")
    if openai_key:
        try:
            return _call_openai(farm_id, message, history, context, tier, openai_key)
        except Exception as e:
            logger.warning("[ai_chat] OpenAI 폴백 실패: %s", e)

    # ③ Ollama 로컬 LLM (폴백 2) — OLLAMA_ENABLED=true 이거나 OLLAMA_HOST 설정 시 시도
    ollama_enabled = _cfg("OLLAMA_ENABLED", "false").lower() in ("1", "true", "yes")
    ollama_host    = _cfg("OLLAMA_HOST", "")
    if ollama_enabled or ollama_host:
        try:
            return _call_ollama(farm_id, message, history, context)
        except Exception as e:
            logger.warning("[ai_chat] Ollama 폴백 실패: %s", e)

    # ④ 규칙 기반 stub (최종 폴백)
    return _rule_based_reply(message, context)


def _call_openai(
    farm_id: str,
    message: str,
    history: list[dict],
    context: dict,
    tier: str,
    api_key: str,
) -> dict:
    """OpenAI API 호출 (Anthropic 대체)."""
    import urllib.request, urllib.parse, json as _json
    model = "gpt-4o-mini" if tier in ("pro", "enterprise") else "gpt-3.5-turbo"
    max_tokens = int(_cfg("AI_CHAT_MAX_TOKENS", "800"))
    system_prompt = _build_system_prompt(context)

    msgs = [{"role": "system", "content": system_prompt}]
    msgs += history[-10:]
    msgs.append({"role": "user", "content": message})

    body = _json.dumps({
        "model": model,
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    timeout = float(_cfg("AI_CHAT_TIMEOUT", "20"))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = _json.loads(resp.read().decode("utf-8"))

    text = raw["choices"][0]["message"]["content"].strip()
    tokens = raw.get("usage", {}).get("total_tokens", 0)
    parsed = _parse_response(text)
    parsed["model_used"] = model
    parsed["tokens_used"] = tokens
    parsed["referenced_data"] = _infer_referenced(message)
    logger.info("[ai_chat] OpenAI farm=%s model=%s tokens=%d", farm_id, model, tokens)
    return parsed


def _call_ollama(
    farm_id: str,
    message: str,
    history: list[dict],
    context: dict,
    model: str = "llama3.2",
) -> dict:
    """Ollama 로컬 LLM 호출 (http://localhost:11434).

    OLLAMA_HOST 환경변수로 호스트 변경 가능 (기본 localhost:11434).
    OLLAMA_MODEL 환경변수로 모델 변경 가능 (기본 llama3.2).
    """
    import urllib.request
    import json as _json

    host  = _cfg("OLLAMA_HOST",  "localhost:11434").rstrip("/")
    model = _cfg("OLLAMA_MODEL", model)
    url   = f"http://{host}/api/chat"
    timeout = float(_cfg("AI_CHAT_TIMEOUT", "20"))

    system_prompt = _build_system_prompt(context)
    msgs = [{"role": "system", "content": system_prompt}]
    msgs += history[-6:]                        # 비용 절감: 최근 6턴
    msgs.append({"role": "user", "content": message})

    body = _json.dumps({
        "model":    model,
        "messages": msgs,
        "stream":   False,
        "options":  {"temperature": 0.7, "num_predict": int(_cfg("AI_CHAT_MAX_TOKENS", "800"))},
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = _json.loads(resp.read().decode("utf-8"))
    except OSError as e:
        raise ConnectionError(f"Ollama 서버 연결 실패 ({host}): {e}") from e

    text   = raw.get("message", {}).get("content", "").strip()
    tokens = raw.get("eval_count", 0)           # 생성 토큰 수
    parsed = _parse_response(text)
    parsed["model_used"]      = f"ollama/{model}"
    parsed["tokens_used"]     = tokens
    parsed["referenced_data"] = _infer_referenced(message)
    logger.info("[ai_chat] Ollama farm=%s model=%s tokens=%d", farm_id, model, tokens)
    return parsed


def _rule_based_reply(message: str, context: dict) -> dict:
    """LLM 키 없을 때 — 실데이터 기반 규칙형 응답기(의도 인식)."""
    crop = context.get("crop", "작물")
    area = context.get("area_m2", 0) or 0
    env  = context.get("env", {}) or {}
    alerts = context.get("alerts", []) or []
    price  = context.get("price_krw_kg", 0) or 0
    yld    = context.get("yield_kg_m2", 0) or 0
    cost   = context.get("cost_per_m2", 0) or 0

    def _g(k):
        v = env.get(k)
        return v if isinstance(v, (int, float)) else None
    temp, hum, co2 = _g("temp_internal"), _g("humidity_int"), _g("co2_ppm")
    vpd, ec, drain = _g("vpd"), _g("ec_dsm"), _g("dr_pct") or _g("dr_pct_mean")
    m = message.lower()
    sugg = ["현재 알림 확인", "오늘 환경 어때?", "수확일 언제야?", "수익 높이는 방법은?"]

    def _fmt(v, u="", d=1):
        return (f"{v:.{d}f}{u}" if isinstance(v, (int, float)) else "—")

    # 1) 관수·양액
    if any(k in m for k in ["관수", "급액", "배액", "함수율", "ec", "양액", "물"]):
        parts = []
        if drain is not None:
            st = "정상(20~30%)" if 20 <= drain <= 30 else ("부족 — 급액량↑" if drain < 20 else "과잉 — 급액량↓")
            parts.append(f"배액률 {_fmt(drain,'%')} → {st}")
        if ec is not None:
            parts.append(f"배액 EC {_fmt(ec,' dS/m')} (정상 3.0~4.5)")
        body = " · ".join(parts) if parts else "현재 관수 센서값이 들어오면 자동 진단합니다."
        reply = (f"💧 {crop} 관수 진단\n{body}\n\n오늘은 일사 적산(J/cm²) 기반으로 P1~P6 단계 관수가 진행됩니다. "
                 f"배액률 12% 미만이면 즉시 추가 관수하세요. 야간(P6)은 dry-back 10~20%가 목표입니다.")
        sugg = ["배액률 정상 범위는?", "야간 dry-back이 뭐야?", "EC 높을 때 조치는?"]

    # 2) 환경·온습도·VPD
    elif any(k in m for k in ["온도", "습도", "환경", "vpd", "co2", "이산화"]):
        reply = (f"🌡️ {crop} 실내 환경\n온도 {_fmt(temp,'°C')} · 습도 {_fmt(hum,'%')} · "
                 f"CO₂ {_fmt(co2,'ppm',0)} · VPD {_fmt(vpd,' kPa',2)}\n\n"
                 f"VPD 적정대는 0.6~1.2 kPa입니다. 1.8↑이면 증산 과다(급액 보완), 0.6↓이면 과습(환기 강화)으로 대응하세요.")
        sugg = ["VPD가 높으면?", "결로 위험 있어?", "환기 언제 해야 해?"]

    # 3) 수확·출하
    elif any(k in m for k in ["수확", "출하", "예측", "언제"]):
        total = round(yld * area) if (yld and area) else None
        reply = (f"🚚 {crop} 수확·출하\n예상 단위수확량 {_fmt(yld,' kg/m²',2)}"
                 + (f" · 전체 약 {total:,}kg" if total else "")
                 + f"\n\n수확 예측은 M2 모델 기반이며, 생육 측정값(초장·엽수)을 입력할수록 정확해집니다. "
                   f"출하는 공동출하(Pool) 단가와 개별 출하를 비교해 결정하세요.")
        sugg = ["공동출하가 유리해?", "생육 측정값 입력하기", "이번 주 시세는?"]

    # 4) 수익·단가·이익
    elif any(k in m for k in ["수익", "매출", "단가", "가격", "이익", "소득", "시세"]):
        rev = round(price * yld * area) if (price and yld and area) else None
        margin = None
        if price and yld and area and cost:
            revv = price * yld * area; costv = cost * area
            margin = round((revv - costv) / revv * 100) if revv else None
        reply = (f"💰 {crop} 수익 현황\n단가 {price:,.0f}원/kg · 예상 매출 "
                 + (f"{rev:,}원" if rev else "—")
                 + (f" · 마진율 약 {margin}%" if margin is not None else "")
                 + "\n\n원가는 C5 수익성 ERP에서 실시간 소득률로 확인할 수 있습니다. "
                   "에너지 피크시간(10~17시) 절감으로 마진을 높일 수 있습니다.")
        sugg = ["원가 절감 방법은?", "에너지비 줄이려면?", "공동출하 단가 비교"]

    # 5) 병해·생리장애
    elif any(k in m for k in ["병해", "질병", "곰팡이", "역병", "벌레", "방제", "노균"]):
        risk = "높음" if (hum and hum >= 85) else ("주의" if (hum and hum >= 75) else "낮음")
        reply = (f"🔬 {crop} 병해 위험\n현재 습도 {_fmt(hum,'%')} 기준 위험도 **{risk}**.\n\n"
                 f"습도 85%↑·결로 지속 시 잿빛곰팡이·노균병 위험이 큽니다. "
                 f"환기로 포차를 높이고, 방제 시행은 F6/G5 화면에서 약제·농도와 함께 기록하세요. 병해는 발생 72시간 전 조기경고를 제공합니다.")
        sugg = ["결로 위험 시간은?", "방제 기록하기", "IPM 체크리스트"]

    # 6) 알림·이상·현황
    elif any(k in m for k in ["알림", "이상", "경보", "현황", "상태", "오늘"]):
        if alerts:
            lines = "\n".join(f"• [{a.get('severity','')}] {a.get('message_ko','')}" for a in alerts[:5])
            reply = f"🔔 현재 활성 알림 {len(alerts)}건\n{lines}\n\n자세한 처방은 홈의 '오늘의 결정' 카드에서 원탭으로 실행할 수 있습니다."
        else:
            reply = (f"✅ 현재 {crop} 농장에 활성 경보가 없습니다.\n온도 {_fmt(temp,'°C')} · 습도 {_fmt(hum,'%')} · VPD {_fmt(vpd,' kPa',2)} 모두 모니터링 중입니다.")
        sugg = ["오늘의 결정 보기", "관수 상태는?", "수확 예측 보기"]

    # 7) 에너지
    elif any(k in m for k in ["에너지", "전기", "전력", "난방", "요금"]):
        reply = ("⚡ 에너지 절감\n한전 시간대별 요금 기준, 피크시간(10~17시)에 난방·LED를 20~50% 자동 감축하면 "
                 "연 350~400만원 절감이 가능합니다. G2 환경화면의 'AI 에이전트(빠른 루프)' 카드에서 현재 절감 상태를 확인하세요.")
        sugg = ["지금 피크시간이야?", "LED 스펙트럼 자동?", "이번 달 전기요금 분석"]

    # 8) 기본 안내
    else:
        reply = (f"안녕하세요! {crop} 농장 AI 상담사입니다. 🌱 (면적 {area:.0f}m²)\n"
                 "관수·환경·수확·수익·병해·알림·에너지에 대해 물어보세요. 농장 실데이터로 답변합니다.\n"
                 "※ 더 정밀한 대화형 분석은 LLM 연동(ANTHROPIC_API_KEY) 시 제공됩니다.")

    return {
        "reply": reply,
        "suggestions": sugg,
        "model_used": "rule_based",
        "tokens_used": 0,
        "referenced_data": _infer_referenced(message),
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
