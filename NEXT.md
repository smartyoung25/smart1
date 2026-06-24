# NEXT — 다음 세션 시작점
> 생성: 2026-06-21 / 마지막 커밋: `ea081d3` pipeline stale candidate 오배포 재발 방지

## 현재 상태 (1줄)
PDCA + 컨설팅 개입 트리거 + 파이프라인 재발방지 완료. 배포 모델 전원 안정 상태.

## 이번 세션 완료
[x] PDCA 연산 오류 5건 수정 (b192c8e)
[x] auth.py send_email 502 수정 (4e61d15)
[x] pipeline: stale candidate 오배포 재발 방지 (ea081d3)
  - train_m2.py/train_m1.py: candidate/ 쓰기 전 shutil.rmtree 청소
  - model_gate.py: _is_fresh() 30분 TTL + stale WARNING 로그
  - train_m2.py: v6 타겟 선택 오류(threshold) -> v4 quick_mape 비교로 복원
  - train_m1.py: m1_meta.json 출력 경로 art_dir -> candidate/ 통일

## 현재 배포 모델 (안정)
| 작물 | MAPE | 타겟 | 버전 |
|------|------|------|------|
| 딸기 | 53.9% | log_yield_ratio | v4 |
| 방울토마토 | 55.7% | log_yield | v4 |
| 완숙토마토 | 55.7% | log_yield_ratio | v4 |
| 참외 | 23.2% | log_yield_ratio | v4 |
| 파프리카 | 32.9% | log_yield_ratio | v4 |

딸기/방울/완숙: MAPE 50%대 -> 데이터 한계 (2018-2021 학습, 농가당 평균 2시즌)
알고리즘 개선 한계 -> ERA5 실측 CSV 또는 2022+ 수확 데이터 확보가 근본 해결책

## 다음 작업 (우선순위 순)

### 즉시
- [ ] 노지 스마트팜 PPT 완성 -- f1~f8 스크린샷 + 특장점 (pptxgenjs)

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
