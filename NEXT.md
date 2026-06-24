# NEXT — 다음 세션 시작점
> 생성: 2026-06-21 / 마지막 커밋: `b192c8e` PDCA 연산 오류 5건 수정

## 현재 상태 (1줄)
EP1~EP6 환경구간 + PDCA 3대 지수(효과성·효율성·성장가능성) + 컨설팅 개입 트리거 + 파이프라인 버그 수정 완료. auth send_email 502 수정 완료.

## 이번 세션 완료
[x] EP1~EP6 환경 관리 구간 시스템 (g2_env.html + climate_plan.py)
[x] PDCA 운영관리 화면 신규 (c25_pdca.html + api/services/pdca.py)
  - 효과성·효율성·성장가능성 3대 지수 게이지
  - 주간 타임라인 + 상세 Plan/Do/Check/Act 카드
  - 일일 EP 준수 현황
[x] 컨설팅 개입 트리거 패널 (pdca/consult 엔드포인트)
  - 효과성 < 40% → 즉각 개입, < 60% → 경고
  - 착과기 D-3 → 작목별 체크리스트 BottomSheet
  - 드리프트 🔴 2작목+ → 보정값 편집 패널
[x] 파이프라인 버그 수정 (retrain_trigger.py --crop 플래그 문제)
[x] M2 재학습: 참외(23.2%) 파프리카(32.9%) 배포 / 딸기·완숙·방울 현행 유지
[x] PDCA 연산 오류 5건 수정 (gp.score/100, overall_grade, CSS 변수 등)
[x] auth.py:393 send_email() 실패 시 HTTP 502 반환 (데모 모드는 링크 반환 유지)

## 다음 작업 (우선순위 순)

### 즉시
- [ ] 노지 스마트팜 PPT 완성 — f1~f8 스크린샷 + 특장점 (pptxgenjs)

### 단기
- [ ] M2 딸기·완숙토마토·방울토마토 MAPE 개선
  - Distribution shift (학습 2018–2021, 운영 2022+) 근본 해결
  - farm_corrections.json 수동 보정 또는 ERA5 CSV 확보 후 재학습
- [ ] IP Insight FTO 보고서 자동생성 (`C:\IPinsight` — G1 탭 다운로드 버튼)
- [ ] IP Insight G6 가치평가 DCF 슬라이더 + Plotly 차트

### 사용자 액션 필요 (Claude 불가)
- ERA5 실측 CSV 확보 → 토마토 M1 재학습
- Let's Encrypt 인증서 교체 (서버 관리자 권한)
- `.env` SMTP_USER·SMTP_PASSWORD·CoolSMS·Slack Webhook 설정

## 서버 실행
```powershell
# smart_farm
$env:PYTHONPATH="C:\smart_farm"; $env:PUBLIC_DEMO="1"
python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos

# IP Insight (별도)
cd C:\IPinsight ; $env:PYTHONIOENCODING="utf-8"
python -m uvicorn api.main:app --port 8001 --reload
python -m streamlit run frontend/app.py --server.port 8503
```

## 주의사항
- SW 캐시 현재 v64 — 화면 변경 시 sw.js CACHE 버전 bump 필수
- `PUBLIC_DEMO=1` 환경: `/api/admin/*` 전부 403
- IP Insight pytest: 반드시 `cd C:\IPinsight`에서 실행 (smart_farm pytest.ini 간섭)
- PCML `release_status`: releasable | internal_only | blocked (`partial` 아님)
- outputs/etl/ parquet 3파일은 master_train.parquet 기반 재생성 (DB ETL 덮어쓰기 주의)
