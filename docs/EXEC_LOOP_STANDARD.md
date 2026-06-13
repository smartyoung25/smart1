# EXEC_LOOP_STANDARD — 화면 실행 폐루프 표준

## 원칙
의사결정·운영 구동 화면은 **표시(display) → 의사결정(decision) → 실행/기록(action·record) → 학습(learning)** 4단계를 갖춘다.
분석 전용(리포트성) 화면은 read-mostly 허용(기록 강제 안 함).

## 기록 메커니즘 (단일 컴포넌트)
- `components/record_sheet.js` `RecordSheet.open({title, fields, onSubmit})` → `logActivity(farm, token, {kind, item, detail, value})` → `POST /api/farms/{id}/activity`.
- `renderRecent(el, farm, token, {kinds, limit})` 로 최근 기록 표시.
- 표준 kind(아이콘): irrigation·disease_check·harvest·env_setpoint·growth·decision_apply·consult·joint_ship·consent·**cost_reduction**·integration_request·education·todo.
- 데이터 학습 피드: 생육 `/api/data/growth`(M1), 수확 `/api/data/harvest`(M2). activity는 이행·보상·리포트 집계(C7·C14).

## 화면별 루프 상태 (현행)
| 화면 | display | decision | action/record | 비고 |
|---|---|---|---|---|
| G3 관수 | ✅ | ✅ Priva/AI | ✅ 관수 승인·기록 | 완결 |
| C17 진단 | ✅ | ✅ 처방 | ✅ 처방 기록 | 완결 |
| G5 병해 | ✅ | ✅ 방제조언 | ✅ **방제 이행 기록**(Stage3) | 완결 |
| C5 ERP | ✅ | ✅ 절감조언 | ✅ **절감 조치 기록**(Stage3) | 완결 |
| G4 생육 | ✅ | ✅ 조언 | ✅ 생육·**수확실측** 기록 | 완결 |
| G1 홈 | ✅ | ✅ DecisionDeck | ✅ onApply(decision_apply) | 완결 |
| C18 문진 | ✅ | — | ✅ 문진 CRUD | 완결 |
| C14 리포트 | ✅ | ✅ To-do | (read-mostly) | 분석전용 허용 |
| G2 환경 | ✅ | ✅ 전략표·AI제어 | ✅ 설정 기록 | 완결 |

## 신규 화면 체크리스트
1. 의사결정 구동이면 RecordSheet 기록 버튼 필수. 2. kind는 표준 목록 재사용. 3. 최근기록 노출. 4. 데모 게이트(`/activity` 허용) 확인.
