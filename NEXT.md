# NEXT — 다음 세션 시작점
> 생성: 2026-06-25 / 마지막 커밋: 진행 중 (M2-eco 조사 완료)

## 현재 상태 (1줄)
M2-eco 제주 노지 5개 작목 조사 완료 — 소득조사+ERA5 구조적 한계 확인, 배포 불가 결론.

## 이번 세션 완료
[x] ETL 버그 수정 (scripts/etl_income_survey.py)
  - 2007~2015 Arrow large_string 타입 → srvar_tot_sqm(실면적) 없는 구형 파일 제외
  - stdar_py=300평 폴백 → yield_per_10a 3배 과대 추정 문제 해결
  - ctynm, dtnm 컬럼 추가 (지역 정보)
  - 최종: 2,702행 (2016~2022, srvar_tot_sqm 정확한 행만)
[x] train_m2_eco.py 대대적 개선
  - TimeSeriesSplit(by year) CV 전환 (GroupKFold by farm → leakage 과소 추정 제거)
  - ERA5 anomaly 피처 추가 (과거 5년 평균 대비 편차)
  - ctynm 인코딩 + ctynm_yield_mean 피처 추가
  - YoY ratio 타겟 모드 (절대 yield 대신 farm_yield_mean 대비 상대 비율 예측)
[x] M2-eco 5개 작목 최종 재학습 (candidate 저장, 배포 미진행)
  - 감귤 절대 MAPE 98%, 마늘 122%, 무 122%, 양파 102%, 양배추 203%
  - model_gate: 전 작목 reject (기준 미달)

## M2-eco 한계 분석 (확정)
소득조사 농가 간 수확량 편차 10~80배 (p2~p98 범위)
→ ERA5 전국 평균으로 설명 불가 (모든 농가에 동일 기후값)
→ farm_yield_mean 베이스라인 자체가 180%+ MAPE
→ 구조적 한계: 데이터 추가 없이 개선 불가

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
- [x] KAMIS 가격 수집 자동화 — Windows 작업 스케줄러 등록 완료 (매일 06:00)
  작업명: `KAASA_KAMIS_PriceCollect` / 다음 실행: 매일 06:00
- [ ] M2-eco 노지 작목: 통계청 농업통계 연도별 평균 수확량 CSV 확보 시 연도 수준 모델 전환 가능

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
