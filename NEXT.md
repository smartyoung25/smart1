# NEXT — 다음 세션 시작점
> 생성: 2026-06-18 / 마지막 커밋: `a83ca9e` Stop hook 권한 설정 + SMART1 스킬 비활성화
> 최근: IP Insight 진단 리뷰 (P1~P4 우선순위 정의)

## 현재 상태 (1줄)
IP Insight 구조 진단 완료. P1 온도/청킹, P2 수치 검증, P3 결제, P4 신뢰성 우선순위 정의. 구현 미시작.

## 이번 세션 목표
[x] IP Insight 구조 진단 및 P1~P4 우선순위 매핑 완료

## 다음 작업 (구현 순)
### P1 (즉시 — 일관성 + 청킹)
- [ ] `base_agent.py:80` — Anthropic `temperature=0` + `system_fingerprint`
- [ ] `pcml_agent.py:636` — 8K토큰 슬라이딩 윈도우 청킹

### P2 (단기 — 정확성 + 파일)
- [ ] `report_pipeline.py:244` — 수치 검증 (PQE ±5점, 청구항 수)
- [ ] `/ip/upload-file` — PDF/HWP 업로드 (pdfminer.six, hwpx)

### P3 (결제 — 별도 스프린트)
- [ ] Toss Payments: initiate → confirm → refund
- [ ] idempotency_key, 크레딧 지급 트랜잭션, 환불 정책

### P4 (신뢰성)
- [ ] 점수 근거 텍스트 노출
- [ ] Groq 429 지수 백오프 (tenacity)

## 주의사항
- IP Insight 구현 시 P1 온도/청킹 우선
- 긴 특허(30page+) PCML 누락 → 청크 병합 필수
- 결제 오류 패턴 3가지: 이중 확인, 크레딧 지급, 정책 명문화
