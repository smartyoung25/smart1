# 기자재·시공업체 참조 DB 갱신 운영 절차서

> WP-2026-0618 과제5 산출물 · 대상: 운영 담당자
> 관련: [build_equipment_reference.py](build_equipment_reference.py), [build_equipment_catalog.py](build_equipment_catalog.py)

## 1. 목적·주기
스마트팜코리아 공식 DB(기자재정보·시공업체리스트, 평가완료 카탈로그)를 서비스 참조 데이터에 반영한다.
**주기: 분기 1회**(공식 DB 신판 배포 시 수시 반영 가능). 멱등 빌더라 `--src`만 바꿔 재실행하면 전량 갱신된다.

## 2. 산출 파일 (api/data/reference/)
| 파일 | 내용 | 빌더 |
|------|------|------|
| `equipment_taxonomy.json` | 공식 분류체계(대분류→표준장치명) | reference |
| `vendor_products.json` | 제조사 자사제품(표준장치명·모델·KC) | reference |
| `vendors.json` | 기업(제조/유통/시공) 디렉터리 | reference |
| `construction_companies.json` | 온실 시공업체 도급순위(1~2군) | reference |
| `equipment_catalog.json` | 평가완료 제품 카탈로그(등급·KC·점수) | catalog |
| `_meta.json` / `_catalog_meta.json` | 출처·버전·집계·**변경분(changes)** | 각 빌더 |
| `_meta_history.json` | **갱신 이력 누적**(빌드마다 append) | reference |

## 3. 실행 절차
1. **원본 확보**: 최신 공식 DB 엑셀을 확보한다. 파일명 끝 `_YYMMDD.xlsx`의 6자리가 `source_version`으로 기록되므로 명명 규칙을 유지한다.
2. **빌더 재실행**(프로젝트 루트에서):
   ```
   python scripts/build_equipment_reference.py --src "C:/path/스마트팜코리아_DB(...)_기자재정보_시공업체리스트_YYMMDD.xlsx"
   python scripts/build_equipment_catalog.py   --src "C:/path/평가완료_카탈로그_YYMMDD.xlsx"
   ```
3. **변경분 확인**: 빌더가 출력하는 `changes`와 `_meta.json`을 검토한다.
   - `changes.<entity>.added / removed` = 신규·삭제 건수, `added_sample` = 신규 항목 예시.
   - `previous_version` → `source_version`으로 버전이 올라갔는지 확인.
   - 누적 이력은 `_meta_history.json`에서 확인.
   - 예상 밖 대량 삭제(removed 급증)는 **원본 컬럼구조 변경** 신호 → 4번 위험대응 참조.

## 4. 배포·검증
1. 참조 API 응답 확인(읽기전용, 서버 재기동 불필요 — 파일 즉시 반영):
   ```
   curl "http://localhost:8000/api/reference/meta"
   curl "http://localhost:8000/api/reference/construction?rank=1군&limit=3"
   curl "http://localhost:8000/api/reference/catalog?q=&limit=3"
   ```
2. 화면 확인: **C16 기자재**(자동완성·등급·KC 배지), **C24 온실 시공업체**(도급순위 검색).
3. 콘솔 에러 0 / API 4xx 0 확인.

## 5. 변경 커밋
```
git add api/data/reference/*.json
git commit -m "chore(reference): 공식 DB YYMMDD 반영 (vendor_products +N, construction ±M)"
```
`_meta_history.json`도 함께 커밋해 갱신 이력을 보존한다.

## 6. 위험요소·대응
| 위험 | 대응 |
|------|------|
| 공식 DB 컬럼 구조 변경 | 빌더 헤더 매핑 방어코드(`_ci`) — 누락 컬럼은 무시. removed 급증 시 헤더 매핑 점검 |
| 대량 삭제(오파싱) | `_meta.changes.removed_sample` 확인 후 원본 시트/헤더 재확인. 이상 시 커밋 보류·이전 버전 유지 |
| 롤백 필요 | `git checkout -- api/data/reference/` 로 직전 커밋 상태 복원 |
| 서비스 영향 | 참조 API는 **읽기전용(GET)** — PUBLIC_DEMO 쓰기 게이트와 무관, 무중단 반영 |

## 7. 롤백
```
git checkout -- api/data/reference/
```
직전 커밋의 참조 데이터로 즉시 복원(API 파일 즉시 반영).
