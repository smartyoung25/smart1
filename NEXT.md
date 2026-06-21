# NEXT — 다음 세션 시작점
> 생성: 2026-06-21 / 마지막 커밋: `cf4557d` 노지 f1~f8 프로세스 안정성 개선

## 현재 상태 (1줄)
프로세스 안정성 수정 완료 (토큰 실패 배너·WS visibility 가드·f3 네비·kpiRisk 동적화). 노지 PPT 제작 중.

## 이번 세션 완료
[x] 프로세스 안정성 진단 및 수정 (cf4557d)
  - f1~f8 `_ensureToken()` 실패 시 amber 배너 표시
  - `data.js` `showConnectError()` 공개 메서드 추가
  - `data.js` WebSocket 화면 숨김 중 재연결 보류 (배터리 절약)
  - `f3_weather.html` 헤더 `노지 ›` back 링크 추가
  - `f1_field.html` kpiRisk 하드코딩 → API hazard_level 동적 바인딩

## 다음 작업 (우선순위 순)

### 즉시
- [ ] 노지 스마트팜 PPT 완성 — f1~f8 스크린샷 + 특장점 (pptxgenjs)

### 단기
- [ ] `api/routers/auth.py:393` — send_email() 실패 시 HTTP 502 반환
- [ ] IP Insight FTO 보고서 자동생성 (`C:\IPinsight` — G1 탭 다운로드 버튼)
- [ ] IP Insight G6 가치평가 DCF 슬라이더 + Plotly 차트

### 사용자 액션 필요 (Claude 불가)
- ERA5 실측 CSV 확보 → 토마토 M1 재학습
- Let's Encrypt 인증서 교체 (서버 관리자 권한)
- `.env` SMTP_USER·SMTP_PASSWORD·CoolSMS·Slack Webhook 설정

## 서버 실행
```powershell
# smart_farm
PYTHONPATH=C:\smart_farm PUBLIC_DEMO=1 python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos

# IP Insight (별도)
cd C:\IPinsight ; $env:PYTHONIOENCODING="utf-8"
python -m uvicorn api.main:app --port 8001 --reload
python -m streamlit run frontend/app.py --server.port 8503
```

## 주의사항
- SW 캐시 v16 — 화면 변경 시 `base.css` 또는 `data.js` CACHE_VERSION bump 필수
- `PUBLIC_DEMO=1` 환경: `/api/admin/*` 전부 403
- IP Insight pytest: 반드시 `cd C:\IPinsight`에서 실행 (smart_farm pytest.ini 간섭)
- PCML `release_status`: releasable | internal_only | blocked (`partial` 아님)
