# 관수통합관리시스템 ↔ smart_farm 연동 작업 로그
> 작성: 2026-05-31 (Cowork 세션)
> 다음 작업: Claude Code (C:\smart_farm 폴더에서 진행)

---

## 완료된 작업 (Cowork에서 구현)

### 1. 신규 파일
| 파일 | 내용 |
|------|------|
| `adapters/irrigation_adapter.py` | P4 시간대별 관수 데이터 → canonical 변수 변환 |

### 2. 수정된 파일
| 파일 | 변경 내용 |
|------|-----------|
| `adapters/base_adapter.py` | VALID_RANGES에 관수 canonical 8개 추가 (wc_mean, wc_max, wc_min, dr_pct_mean, ec_drain, supply_total, irr_count, nl_pct) |
| `api/routers/farmer.py` | `POST /api/farms/{farm_id}/irrigation` 엔드포인트 추가 |
| `pipeline/incremental_etl.py` | IRR_COLS, 관수 컬럼 매핑 추가 |
| `pipeline/train/prep_m1.py` | IRR_BASE 피처 lag/rolling 포함 |

---

## 다음 작업 목록 (Claude Code에서 진행 권장)

### 우선순위 1: 관수 데이터 DB 저장
- `api/routers/farmer.py`의 `/irrigation` 엔드포인트가 현재 로그만 기록
- PostgreSQL `irrigation_records` 테이블 생성 + 실제 저장 구현
- `pipeline/incremental_etl.py`에서 irrigation_records 읽어 parquet에 편입

### 우선순위 2: 생육 데이터 manual_input 연동
- 관수시스템 HTML의 `sendGrowthToSmartFarm()` → `POST /api/farms/{id}/manual-input`
- 현재 manual_input_adapter.py가 growth_survey 타입을 처리하나 DB 저장 경로 확인 필요

### 우선순위 3: ML 모델 재학습 (관수 피처 포함)
```bash
# 작업 순서
cd /경로/smart_farm
python pipeline/incremental_etl.py --crop 딸기 --with_irrigation
python pipeline/train/prep_m1.py 딸기
python pipeline/train/train_m1.py 딸기
```
- 현재 Stage1 R² 딸기=0.254 → 관수 피처 추가 후 목표 R² > 0.45

### 우선순위 4: KAMIS 실시간 시세 연동 확인
- `GET /api/admin/prices/latest` → 관수시스템 KAMIS 패널 연동
- kamis_fetcher.py의 캐시 갱신 주기 확인

---

## 관수통합관리시스템 HTML 연동 포인트

```
C:\irrigation\관수통합관리시스템.html (263,591 bytes)

연동 엔드포인트:
  POST /api/farms/{farm_id}/irrigation     ← P4 관수 데이터 전송
  POST /api/farms/{farm_id}/manual-input   ← 생육 데이터 전송
  GET  /api/admin/prices/latest            ← KAMIS 시세 조회
  WS   /ws/farms/{farm_id}/sensors         ← 실시간 IoT 자동 입력
  GET  /health                             ← 연결 테스트
  POST /api/v2/recommend                   ← AI 수익 최적화 추천

농장정보 탭에서 API URL·Farm ID·JWT 설정 가능
```

---

## irrigation_adapter.py 테스트

```bash
cd C:\smart_farm
python -c "
from adapters.irrigation_adapter import adapt_irrigation
result = adapt_irrigation({
    'farm_id': 'farm_001', 'crop': '딸기', 'date': '2026-05-31',
    'slab_vol_l': 15.0, 'max_wt_kg': 14.8, 'sunset_wt_kg': 13.5,
    'periods': [
        {'period':1,'supply_ml':150,'drain_ml':0,  'ec':2.5,'slab_wt_kg':12.5},
        {'period':2,'supply_ml':300,'drain_ml':80, 'ec':2.4,'slab_wt_kg':14.2},
        {'period':3,'supply_ml':400,'drain_ml':150,'ec':2.6,'slab_wt_kg':14.8},
        {'period':4,'supply_ml':200,'drain_ml':100,'ec':2.7,'slab_wt_kg':13.5},
    ]
})
for r in result.records: print(r.canonical_name, '=', r.value)
"
# 예상 출력: wc_mean=91.7, dr_pct_mean=28.5, ec_drain=2.55, supply_total=1050, irr_count=4, nl_pct=8.8
```
