# NEXT — 다음 세션 시작점
> 생성: 2026-06-21 / 마지막 커밋: `ae2bd60` KAMIS 가격 수집 + 수확 기록

## 현재 상태 (1줄)
KAMIS 가격 수집 완료(5종/매일 실행 누적). 딸기는 비수기(6월) 거래 없음 — 12월 이후 자동 수집.

## 이번 세션 완료
[x] 운영 데이터 동기화 + gitignore 보강 (fc8a489)
  - data/collected/growth/ 생육기록 120개 (딸기 100, 방울 20)
  - api/data/onboarding/ 농가 3개 신규
  - 로컬DB/빌드산출물/임시파일 gitignore 추가
[x] M2 v4c — farm_yield_mean CV leakage 수정 (1557c05)
  - expanding window (이전 시즌 누적 평균)으로 교체 → CV 정직화
  - 상관 피처 자동 제거 |r|>0.95 (42→35개)
  - 전 작목 정직한 기준선 재설정 (강제 배포)
[x] c25_pdca.html 로드 중 고착 3종 수정 (3d51073)
  - _apiFetch r.ok 체크 추가
  - _loadAll token null 가드
  - catch 블록: 7개 요소 전체 에러 표시
[x] SW 캐시 v64 → v65 bump

## 현재 배포 모델 (v4c 정직한 CV MAPE)
| 작물 | MAPE | 비고 |
|------|------|------|
| 참외 | 27.3% | 실용 수준 ✅ |
| 방울토마토 | 70.6% | 방향성 참고 |
| 파프리카 | 68.6% | 방향성 참고 |
| 딸기 | 102.4% | 데이터 부족 |
| 완숙토마토 | 137.5% | 데이터 부족 |

※ 이전 v4b MAPE(53~55%)는 leakage로 과소 추정된 값. v4c가 실제 배포 성능.
※ 근본 해결: 2022+ 실수확 데이터 수집 → 딸기/완숙 재학습

## 다음 작업 (우선순위 순)

### 사용자 액션 필요 (Claude 불가)
- **2022+ 실수확 데이터** 확보 → 딸기/완숙 M2 재학습 (근본 해결)
- Let's Encrypt 인증서 교체 (서버 관리자 권한)
- `.env` SMTP_USER/SMTP_PASSWORD/CoolSMS/Slack Webhook 설정

### 단기 (Claude 수행 가능)
- [ ] IP Insight G1 탭 — FTO 보고서 자동생성 다운로드 버튼
- [ ] IP Insight G6 — 가치평가 DCF 슬라이더 + Plotly 차트
- [ ] KAMIS 가격 수집 자동화 — Windows 작업 스케줄러 등록 (매일 06:00)
  `python scripts/fetch_kamis_price.py --all`

## 서버 실행
```powershell
$env:PYTHONPATH="C:\smart_farm"; $env:PUBLIC_DEMO="1"
python -m uvicorn api.main:app --port 8000
cloudflared tunnel --config deploy/cloudflare/config.yml run kaasa-smartos
```

## 주의사항
- SW 캐시 현재 **v65** — 화면 변경 시 sw.js CACHE 버전 bump 필수
- `PUBLIC_DEMO=1` 환경: `/api/admin/*` 전부 403
- M2 재학습 후 반드시 gate dry_run 먼저 확인 (`--dry_run` 플래그)
- candidate/ 는 학습 스크립트가 자동 청소 — 수동 파일 넣지 말 것
- IP Insight pytest: 반드시 `cd C:\IPinsight`에서 실행 (smart_farm pytest.ini 간섭)
