# 실데이터 주입 검증 (제주 공공데이터셋)

출처: 사용자 제공 Google Drive 제주 농업 데이터셋(45종). API 키가 아닌 **실데이터 파일(parquet)**.
지역 매칭(`sido`에 '제주' 포함) 시 Mock→실데이터 자동 전환, 비제주는 Mock 폴백 유지.

## 주입·검증 완료
| 연동 | 원천 데이터 | 적재 | 엔드포인트 source | 검증 |
|------|------------|------|------------------|------|
| **흙토람 토양** | 토양검정 2024 (13,842필지) | `api/data/real/soil_jeju.json` | `naas_soil_real` | 서귀포시→ph 5.66·EC 1.943·유기물 106.4 (6,653필지 평균) |
| **팜맵 필지** | 농경지전자지도 2024 (276,491필지) | `api/data/real/parcels_jeju.json` | `farmmap_real` | 서귀포 강정동→4,601필지 764ha 실 샘플(시설·과수·비경지) |

→ `/field/soil`·`/field/parcels`·`/field/cluster`(F8)가 제주 농장에 실데이터 제공.
재현: `python scripts/import_real_soil.py` / `python scripts/import_real_parcels.py`

## 주입 불필요/불가
| 항목 | 사유 |
|------|------|
| **기상(제주 AWS)** | F3 기상은 이미 LIVE(KMA ASOS + Open-Meteo). AWS 과거 관측은 실시간 예보에 미반영 — 주입 가치 낮음 |
| **위성 NDVI** | 폴더에 위성 API/타일 없음. `SATELLITE_NDVI_URL` 키 주입 시 프록시→sentinel-2 전환(구조 완비) |
| **LLM·알림** | 데이터셋 무관. `.env` 키(`ANTHROPIC_API_KEY`·`SLACK_WEBHOOK_URL`·`COOLSMS_*`) 필요 |

## 추가 주입 가능(미적용)
감귤 생육조사·소득조사·디지털트랩(예찰)·도매시장 경매 등 — 작황/경영/병해/시세 정밀화에 활용 가능.
대용량 parquet은 `data_real/`(gitignore)에 받고 importer로 집계분만 `api/data/real/`에 적재.

## 점검
`python scripts/check_integrations.py` → 흙토람·팜맵 실적재 행 + 연동 상태 일괄 확인.
