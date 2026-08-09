# 노지 표준재배력 SSOT — 근거 매니페스트 & 진행 상태 (세션 핸드오프)

> **목적**: `models/cultivation_calendar.json`(SSOT)의 각 작목·품종 재배력이 **어떤 출처**에서 왔는지, 무엇이 아직 **coarse(작형월 파생)**이고 무엇이 **정밀(외부 표준재배력 적재)**인지 추적한다. 컨텍스트 한계를 넘어 다음 세션이 이어받도록 진행 상태를 여기 기록한다.
> **정직화 규칙**: 출처 없는 시기/날짜/품종 값은 **적재 금지**. coarse 값은 `precision:"coarse"`로 표기하고, 정밀 승격 시 `source`를 외부 표준재배력으로 교체한다.

## 로드맵 (Phase)
- **Phase 0 (완료)**: SSOT 스키마 + 로더(`models/cultivation_calendar.py`) + 본 매니페스트. seed = crop_config 작형월(수기 큐레이션) 기반 **coarse 표준 작형**(6작목 기본 품종).
- **Phase 1 (데이터 의존)**: 아래 표의 "필요 출처"를 확보해 정밀 재배력(품종군·순 단위 파종/정식/수확·생육단계·병해 발생시기)으로 승격. `scripts/import_cultivation_calendar.py`로 적재.
- **Phase 2~4**: 노지 재배력·기준·코멘트 화면 / 필지 실측 앵커 / 농작업 추천·대행(계획 파일 참조).

## 작목별 적재 상태

| 작목 | 현재(seed) | precision | 필요 출처(Phase1 승격) |
|------|-----------|-----------|----------------------|
| 감귤 | 노지 온주 수확 10~12월 | coarse | 농사로 감귤 표준재배력(품종군: 극조생·조생·중생, 전정·방제 시기) |
| 월동무 | 파종 9~10 / 수확 12~2 | coarse | 제주 농업기술원 월동무 재배력 |
| 당근 | 파종 8~9 / 수확 12~2 | coarse | 농사로 당근 표준재배력(제주 월동 작형) |
| 양배추 | 정식 8~9 / 수확 12~2 | coarse | 농사로 양배추 표준재배력(월동 결구) |
| 마늘 | 난지형 파종 9~10 / 수확 5~6 | coarse | 농사로 마늘(난지형) 표준재배력(품종: 남도·대서 등) |
| 양파 | 정식 10~11 / 수확 5~6 | coarse | 농사로 양파 표준재배력(품종군: 조생종·중만생종) |

## 근거 있는(정직) 보조 자산 — 이미 연동
- **기후 평년값**: `api/data/real/era5_*_monthly.json` + `api/services/climatology.get_climatology` — 작목×달력월 기온·일사·강수·**GDD(적산온도)**, 실측(ERA5). 로더가 `climate_normal`로 병합.
- **작목 기준온도·Kc**: `models/crop_config.py`(t_base, FAO-56 kc_stages 인용).
- **병해**: `models/m5_disease.assess_disease_3axis`(노지 `_CROP_PRIORITY`, **온실 8병해 농학 근사** — "근사" 라벨 유지).

## ⚠️ 창작 금지(원천 없음 — Phase1 출처 확보 전까지 미적재)
- 품종별(조생/중생/만생) 정식/수확 **날짜**·생육단계 전환 시점.
- 노지 작목 전용 병해 발생 임계·시기 prior(현재 온실 근사).
- 성숙·수확 판정 기준.

## 승격 절차(다음 세션용)
1. 위 표 "필요 출처"에서 공개 표준재배력 표를 확보(사용자 제공/지정).
2. `scripts/import_cultivation_calendar.py`로 `cultivation_calendar.json`의 해당 작목 `varieties`에 품종군 추가, `precision:"standard"`, `source`=출처 표기.
3. 이 매니페스트 표의 precision·상태 갱신.
