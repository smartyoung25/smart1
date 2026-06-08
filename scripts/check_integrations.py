# -*- coding: utf-8 -*-
"""외부 연동 상태 점검 — 각 통합의 live/fallback/missing + 활성화 경로 안내.
사용: python scripts/check_integrations.py
"""
import os, json, urllib.request, urllib.error, sys
# .env 로드
try:
    for ln in open(".env", encoding="utf-8"):
        ln=ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k,v=ln.split("=",1); os.environ.setdefault(k, v.strip())
except Exception: pass

B="http://localhost:8000"
def _tok():
    try:
        r=urllib.request.urlopen(urllib.request.Request(f"{B}/api/v1/auth/token",
            data=json.dumps({"username":"admin","password":"1250"}).encode(),
            headers={"Content-Type":"application/json"}), timeout=8)
        return json.load(r)["access_token"]
    except Exception: return None
def _get(path, T):
    try:
        r=urllib.request.urlopen(urllib.request.Request(f"{B}{path}", headers={"Authorization":"Bearer "+(T or "")}), timeout=12)
        return json.load(r)
    except Exception: return None
def has(k): return bool(os.environ.get(k))

T=_tok()
print("="*66)
print(" KAASA SmartOS 외부 연동 상태")
print("="*66)
rows=[]
# 1) KAMIS 시세
rev=_get("/api/farms/farm_001/revenue", T) or {}
src=rev.get("price_source") or rev.get("source","")
rows.append(("KAMIS 도매시세", "🟢 LIVE" if "kamis" in str(src) else "🟠 폴백", f"source={src}", "KAMIS_API_KEY"))
# 2) KMA 기상
wf=_get("/api/farms/farm_001/environment/weather/forecast?days=7", T) or {}
ws=wf.get("source","")
rows.append(("KMA 기상/ASOS", "🟢 LIVE" if "kma" in str(ws) else "🟠 폴백", f"source={ws}", "KMA_SERVICE_KEY"))
# 3) 공공데이터(DATA_GO_KR) — RDA/NCPMS/aT
rows.append(("공공데이터(NCPMS·aT·RDA)", "🟢 키있음" if has("DATA_GO_KR_SERVICE_KEY") else "⚪ 미설정", "DATA_GO_KR", "DATA_GO_KR_SERVICE_KEY"))
rows.append(("농진청(작물·병해 표준)", "🟢 키있음" if has("RDA_API_KEY") else "⚪ 미설정", "RDA", "RDA_API_KEY"))
# 4) 흙토람/팜맵 노지
soil="🟢 직연동" if has("NAAS_SOIL_API_URL") else ("🟡 폴백(DATA_GO_KR)" if has("DATA_GO_KR_SERVICE_KEY") else "⚪ 미설정")
rows.append(("흙토람 토양", soil, "NAAS_SOIL_API_URL", "NAAS_SOIL_API_URL"))
rows.append(("팜맵 필지", "🟢 직연동" if has("FARMMAP_API_URL") else "⚪ Mock", "FARMMAP_API_URL", "FARMMAP_API_URL"))
# 5) LLM 챗봇
if has("ANTHROPIC_API_KEY"): llm="🟢 Claude"
elif has("OPENAI_API_KEY"): llm="🟢 OpenAI"
elif os.environ.get("OLLAMA_ENABLED","").lower() in ("1","true","yes"): llm="🟡 Ollama(로컬)"
else: llm="🟠 규칙형 폴백"
rows.append(("AI 챗봇 LLM", llm, "ANTHROPIC/OPENAI/OLLAMA", "ANTHROPIC_API_KEY"))
# 6) 알림
rows.append(("Slack 알림", "🟢 설정됨" if has("SLACK_WEBHOOK_URL") else "⚪ 미설정", "SLACK_WEBHOOK_URL", "SLACK_WEBHOOK_URL"))
rows.append(("SMS(CoolSMS)", "🟢 설정됨" if (has("COOLSMS_API_KEY") and has("COOLSMS_API_SECRET")) else "⚪ 미설정", "COOLSMS_*", "COOLSMS_API_KEY"))
rows.append(("이메일(SMTP)", "🟢 인증설정" if (has("SMTP_USER") and has("SMTP_PASSWORD")) else "⚪ 인증미설정", "SMTP_USER/PASSWORD", "SMTP_USER"))

print(f"{'연동':28}{'상태':>16}  비고")
print("-"*66)
for name,st,note,_ in rows:
    print(f"{name:28}{st:>16}  {note}")
live=sum(1 for _,s,_,_ in rows if "LIVE" in s or "🟢" in s)
print("-"*66)
print(f"연동 {live} / 폴백·미설정 {len(rows)-live}")
print("\n미연동 활성화: .env 에 해당 키를 채우면 코드 수정 없이 자동 전환됩니다.")
print(" · LLM:    ANTHROPIC_API_KEY (또는 Ollama 모델 pull: 'ollama pull llama3.2')")
print(" · 흙토람: NAAS_SOIL_API_URL (data.go.kr 흙토람 OpenAPI), 팜맵: FARMMAP_API_URL")
print(" · 알림:   SLACK_WEBHOOK_URL / COOLSMS_* / SMTP_USER·PASSWORD")
