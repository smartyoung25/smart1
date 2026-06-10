# 온프레미스 추론 · 연합학습(Federated) 설계 — KAASA SmartOS

> 질문 "농장 입력에 따른 학습을 클라우드·온프레미스 양쪽에 적용할 수 있는가"에 대한
> 아키텍처 답변 + 경량 스캐폴드(`pipeline/federated/`).

## 현재 구현 상태 (사실)

| 구성 | 상태 | 근거 |
|------|------|------|
| 클라우드 중앙 재학습 폐루프 | **구현됨** | activity 적재→`new_rows≥500`→재학습 트리거→`model_gate` 자동배포 (`pipeline/state/retrain_history.json` 실기록) |
| 농장별 보정(Layer 2) | **구현됨** | `models/artifacts/<crop>/farm_corrections.json` → `models/m2_yield._load_corrections()`가 추론 시 `factor` 적용 |
| 온프레미스 **추론** | **즉시 가능** | 모델이 `.pkl` 파일 — 농장 게이트웨이에 동일 아티팩트 배포 시 중앙 API 없이 로컬 추론 |
| 온프레미스/엣지 **학습** | **스캐폴드 단계** | 본 문서 + `pipeline/federated/` (아래). 프로덕션 연합학습(Flower)은 미배선 |

## 핵심 아이디어 — 파라미터만 공유

중앙 M2 모델은 **공통 배포**하고, 각 농장의 **편향 보정계수만** 현장에서 산출해
**스칼라 1개만 업로드**한다. 실수확·환경 원본은 농장을 떠나지 않는다.

```
[농장 온프레미스/엣지]                         [중앙 클라우드]
 실수확·환경 원본 ──┐                          공통 M2 모델(.pkl) 배포 ↓
 공통 M2로 예측 ────┤  local_correction.py      ┌────────────────────┐
 raw_geo=geomean(   │  → {farm_id, factor, n}   │ aggregate.py       │
   실수확/예측)     │  ===== 업로드 =====▶      │ farm_corrections   │
 factor=raw_geo^shr │  (원본 미반출)            │  .json 병합        │
                    └───────────────────────────└────────────────────┘
                         추론 시 예측 × factor (농장 맞춤)
```

### 수식 (중앙 파이프라인과 동일)
```
raw_geo = geomean(actual_yield_i / model_pred_i)   # 농장 편향(기하평균)
shrink  = min(n, 3) / 3                             # 관측 적을수록 1.0로 수축
factor  = raw_geo ** shrink                         # 무보정(1.0) 쪽 베이지안 수축
```
`pipeline/federated/local_correction.py`가 중앙 `farm_corrections.json` 값을 재현
(검증: 경남_거창_051 raw_geo 1.2077·n2 → factor≈1.134, 중앙 1.1385와 반올림 내 일치).

## 배포 토폴로지 3종

| 모드 | 추론 | 학습 | 원본 위치 | 용도 |
|------|------|------|-----------|------|
| **클라우드(현행)** | 중앙 API | 중앙 재학습 | 중앙 수집 | 표준 SaaS |
| **온프레미스 추론** | 농장 로컬(.pkl) | 중앙 | 중앙 수집 | 통신 불안정·저지연 |
| **연합(federated)** | 농장 로컬 | 농장 로컬 보정+중앙 공통모델 | **농장 잔류** | 개인정보·영업비밀 민감 |

## 프로덕션 연합학습으로 확장하려면 (남은 일)
1. **전송 계층**: `POST /api/federated/correction` (농장→서버, 인증·서명). 현재는 함수 호출 수준 스캐폴드.
2. **엣지 러너**: 농장 게이트웨이에서 야간 `local_correction` 실행(현장 실측 적재분 대상).
3. **공통모델 연합평균**: 보정계수를 넘어 M2 가중치까지 공유하려면 **Flower/PySyft** 도입(`technical-spec.md` Phase 3~4 로드맵) — FedAvg로 파라미터만 평균.
4. **보안**: 차등프라이버시(노이즈)·Secure Aggregation으로 단일농장 역추정 차단.

## 스캐폴드 파일
- `pipeline/federated/local_correction.py` — 농장 로컬 보정계수 산출(원본 미반출), self-test 포함
- `pipeline/federated/aggregate.py` — 업로드 파라미터를 `farm_corrections.json`에 병합(기존 추론과 호환)

> 정직한 한계: 본 스캐폴드는 **보정계수(Layer 2) 연합**까지를 충실히 구현한다.
> 모델 가중치 자체의 연합평균(FedAvg)은 Flower 도입이 선행돼야 하며 아직 미구현이다.
