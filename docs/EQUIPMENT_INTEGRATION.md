# 농가 시설 기자재 구축 내역 & 이기종 통합 입력 스펙

> 목적: 농가별로 제각각인 시설 기자재(복합환경제어기·센서·양액기·관개설비)를 표준 분류로 정리하고,
> 제조사·프로토콜이 다른 **이기종 장비를 동일 표준변수로 통합**하기 위한 입력 항목을 규정한다.
> 기계가독 스키마: `api/data/equipment_schema.json` · 표준변수: `api/data/variable_registry.py`

---

## 1. 시설 기자재 구축 내역 (표준 분류 8군)

| 군 | 분류 | 범위 | 대표 기자재 |
|----|------|------|-------------|
| A | 환경제어 액추에이터 | 온실 | 난방기(온풍·온수·지열), 천창/측창 개폐, 순환·유동팬, 차광·보온 스크린, CO₂ 발생기, 포그·미스트 |
| B | 관수·양액 | 공통 | 양액기(믹서), 도징펌프(A/B/산), 관수 주펌프, 구역 전자밸브, 드리퍼·베드, 유량계, 역세 필터 |
| C | 환경·근권 센서 | 공통 | 온습도, 일사·PAR, 지온, CO₂, EC, pH, 배지 함수율, 수분장력계, 토양수분 프로브(노지), 강우 |
| D | 기상 관측 | 노지 | AWS, 풍향·풍속, 우량계, 외부 온습도, 동상해 감지 |
| E | 에너지·전력 | 공통 | 전력량계, 인버터, 보일러, 히트펌프, 축열조, 태양광, 수전설비 |
| F | 노지 관개 설비 | 노지 | 관정·양수펌프, 스프링클러, 점적, 관수 컨트롤러, 여과기, 벤츄리 비료주입기 |
| G | 영상·보안 | 공통 | 생육 카메라, CCTV, 출입통제, 병해 영상진단 |
| H | 제어·통신 | 공통 | 복합환경제어기, PLC·제어반, 게이트웨이, 엣지 컨트롤러, 네트워크(유선·LTE·LoRa) |

농가 구축 내역서 = 위 분류별로 **설치 장비 목록 + 수량 + 설치위치(동/구역/필지) + 설치일**.

---

## 2. 이기종 통합 입력 스펙 (장비 1대당 = 매핑표 1행)

### 2-1. 식별 (Identity)
| 항목 | 입력 | 비고 |
|------|------|------|
| 장비 ID | text(필수) | 농가 내 고유 |
| 분류 / 장비 종류 | select(필수) | 8군 → 세부 장비 |
| 설치 위치 | text | 1동 2구역 / 3번 필지 |
| 설치일 | date | 감가·교체주기 |

### 2-2. 제조사 (Vendor)
제조사: text(필수) — 예: 프리바·호겐도른·그린씨에스·우성하이텍·신한에이텍·씨드로닉스 / 모델명 / 펌웨어 버전

### 2-3. 통신 (Comm) — **이기종 핵심**
| 항목 | 입력 |
|------|------|
| 프로토콜(필수) | MQTT · Modbus-RTU(RS485) · Modbus-TCP · BACnet · OPC-UA · LoRaWAN · HTTP/REST · RS232 · 디지털접점(DI/DO) |
| 주소(IP/호스트) | 192.168.0.x 또는 토픽 prefix |
| 포트 | 502 / 1883 … |
| 슬레이브/유닛 ID | Modbus slave_id, LoRa devEUI |
| 인증(계정/키) | 민감정보 — 별도 보관 |

### 2-4. 데이터 포인트(태그) — 장비당 N개
| 항목 | 입력 | 예 |
|------|------|----|
| 포인트명/태그 | text(필수) | AI001 / holding_reg_40001 / sensors/temp |
| 주소(레지스터/토픽) | text | 40001 / farm/zone1/temp |
| 데이터형 | float·int16·uint16·int32·bool·string | |
| 단위 | text | °C, %, ppm, dS/m, ml, W |
| 배율·오프셋 | number | raw×scale+offset (원시값 보정) |
| 읽기/쓰기 | read·write·read/write | 센서=read, 제어=write |
| 수집 주기(초) | number | 기본 60 |
| **표준변수 매핑** | select | ↓ canonical_name |

### 2-5. 표준변수 매핑 (제조사 무관 통합의 핵심)
각 데이터 포인트를 `variable_registry`의 **표준 변수명**으로 매핑하면, 화면·AI 모델은 제조사·프로토콜을 몰라도 동일하게 사용한다.

`temp_internal · temp_external · humidity_int · co2_ppm · solar_rad · soil_temp · wind_speed_ext · ec_dsm · ph · rainfall_detect · drain_pct · supply_ml · water_content_pct · plant_height_cm · leaf_count · fruit_set_count · stem_diameter_mm · power_kwh · heating_temp_set · vent_open_pct · co2_target_ppm`

### 2-6. 제어(쓰기) 표준 명령
이기종 제어기에 **동일 명령**을 내리기 위한 표준 커맨드:
`heating_temp_set(°C) · vent_open_pct(%) · screen_pct(%) · co2_target_ppm · irrigation_run(ml) · valve_zone(on/off)`

---

## 3. 통합 아키텍처 (개념)

```
[이기종 장비]  ──프로토콜별 어댑터──▶  [엣지 게이트웨이]  ──표준변수 매핑──▶  [KaasaData 표준 레이어]
프리바(Modbus-TCP)                     (scale/offset 보정,                    canonical_name 단일 인터페이스
호겐도른(OPC-UA)                        poll, 토픽/레지스터 파싱)              → 화면·AI 모델·제어 명령
LoRa 센서(LoRaWAN)
국산제어기(RS485)
```

- **읽기**: 장비 raw → 보정(scale·offset) → canonical_name → 센서 스트림(WS/REST)
- **쓰기**: 표준 명령(heating_temp_set 등) → 장비별 어댑터가 프로토콜 변환 → 액추에이터

---

## 4. 앱 반영 방안 (제안)

1. **C1 농장세팅에 "기자재·장비" 단계 추가** 또는 **신규 화면 `c16_equipment.html`**:
   - 분류별 장비 등록(식별·제조사·통신·데이터포인트)
   - 데이터포인트 → 표준변수 매핑 UI
2. **저장**: `POST /api/farms/{id}/equipment` (장비 인벤토리 + 매핑) — DB/JSON
3. **연동 시**: 매핑표대로 게이트웨이가 표준변수 스트림 생성 → 기존 화면 그대로 동작
4. **device_alert.js**와 연계: 장비 online/battery 상태를 인벤토리 기준으로 표시

> 현재 산출물: 분류·입력 스펙 표준화(본 문서 + equipment_schema.json). UI/엔드포인트는 다음 단계.
