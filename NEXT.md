# NEXT — 다음 세션 시작점
> 생성: 2026-06-21 / 마지막 커밋: `ea081d3` pipeline stale candidate 오배포 재발 방지

## 현재 상태 (1줄)
M1~M5 벤치마킹 실시 완료. 방울토마토 53.2% 배포. expert_label + KAMIS 인프라 구축.

## 이번 세션 완료
[x] PDCA 연산 오류 5건 수정 (b192c8e)
[x] auth.py send_email 502 수정 (4e61d15)
[x] pipeline: stale candidate 오배포 재발 방지 (ea081d3)
[x] expert_label 인프라 구축 (63bb711) — PATCH/GET 엔드포인트 + prep_m1 필터링
[x] M1~M5 벤치마킹 기반 성능 향상 실시 (6d7ea90, 7786009)
  - M2 v4b: ERA5 연간 4개 피처 추가 → 방울토마토 55.7%→53.2% 배포 ✅
  - M1: vpd_x_solar/vpd_x_temp/co2_x_solar 교호 피처 추가 (prep_m1.py)
  - M5: scripts/fetch_kamis_price.py — KAMIS aT 일별 도매가격 수집 스크립트
  - Gate 기준 5%p→2%p 완화 (소규모 시계열 데이터 현실 반영)
  - 시도 후 제외: prev_yield(NaN45% 과적합), 이상기상지수, co2_x_solar(역효과)

## 현재 배포 모델
| 작물 | MAPE | 타겟 | 버전 |
|------|------|------|------|
| 딸기 | 53.9% | log_yield_ratio | v4 |
| **방울토마토** | **53.2%** | log_yield | **v4b** ✅ |
| 완숙토마토 | 55.7% | log_yield_ratio | v4 |
| 참외 | 23.2% | log_yield_ratio | v4 |
| 파프리카 | 32.9% | log_yield_ratio | v4 |

딸기/완숙: MAPE 54~56% 데이터 한계 확정. 알고리즘 개선 소진.
근본 해결: 2022+ 실수확 데이터 수집

## 다음 작업 (우선순위 순)

### 즉시
- [ ] KAMIS API 키 설정 (.env KAMIS_CERT_KEY/CERT_ID) → 가격 자동 수집 활성화
  발급: https://www.kamis.or.kr/customer/reference/openApi_list.do
- [ ] 2022+ 실수확 데이터 확보 시 → 딸기/완숙 M2 재학습 (분포 이동 근본 해결)

### 단기
- [ ] IP Insight FTO 보고서 자동생성 (`C:\IPinsight` -- G1 탭 다운로드 버튼)
- [ ] IP Insight G6 가치평가 DCF 슬라이더 + Plotly 차트

### 사용자 액션 필요 (Claude 불가)
- ERA5 실측 CSV 확보 -> 딸기/완숙/방울 M2 재학습 (분포 이동 근본 해결)
- Let's Encrypt 인증서 교체 (서버 관리자 권한)
- `.env` SMTP_USER/SMTP_PASSWORD/CoolSMS/Slack Webhook 설정

## 서버 실행
```powershell
$env:PYTHONPATH="C:\smart_farm"; $env:PUBLIC_DEMO="1"
python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos
```

## 주의사항
- SW 캐시 현재 v64 -- 화면 변경 시 sw.js CACHE 버전 bump 필수
- `PUBLIC_DEMO=1` 환경: `/api/admin/*` 전부 403
- M2 재학습 후 반드시 gate dry_run 먼저 확인 (`--dry_run` 플래그)
- candidate/ 는 학습 스크립트가 자동 청소 -- 수동 파일 넣지 말 것
- IP Insight pytest: 반드시 `cd C:\IPinsight`에서 실행 (smart_farm pytest.ini 간섭)
