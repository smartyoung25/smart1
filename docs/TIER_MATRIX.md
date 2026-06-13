# TIER_MATRIX — 등급별 접근 경로 (단일 출처: api/data/tier_features.json)

> 화면: **C22 등급 비교**(`screens/c22_tiers.html`) — `/api/farms/{id}/billing/features` 실시간 반영.
> 게이팅: 백엔드 402(`billing.py` `tier_rank>=min_tier`) + 프론트 오버레이(`components/tier_guard.js`) + 네비 잠금(`index.html` SCREEN_TIER).

## 등급 (rank·요금·AI쿼터)
| 등급 | rank | 요금/월 | AI 상담 |
|---|---|---|---|
| basic 기본 | 1 | 무료 | 0회 |
| smart 스마트 | 2 | 79,000 | 30회 |
| pro 프로 | 3 | 199,000 | 200회 |
| enterprise 엔터프라이즈 | 4 | 499,000 | 무제한 |

## 등급별 접근 (메뉴/기능 — 누적)
- **basic**: 통합홈(C3)·온실홈(G1)·환경기본(G2 수동입력)·생육잔여일(G4 GDD)·KAMIS 통계시세·기본매출·기본비용·종합진단(C17)·문진(C18)·역량(C19)·기자재(C16)·연동신청(C21)·공동출하 조회(C12). 노지 F1/F2/F3/F5/F7.
- **smart(+)**: G3 관수·양액 Period·배액률·함수율, IoT센서·ASOS·7일예보·이상감지, G4 수확량예측(M2)·병해기본, KAMIS 실시간·가격이력, 비용 항목분석·m²·손익예측, What-if 단일, AI비서(C13). 노지 F4/F6.
- **pro(+)**: G2 VPD+작기단계, G3 야간소실·흡수효율·드레인EC, G4 수확량 신뢰구간·병해상세, 시장 ML예측·최적환경, 이익률, What-if 멀티·권고 3분해·권고 적용(승인)·히트맵·모델지표, AI 진단(C4)·GPT-4o.
- **enterprise(+)**: 완전자동 권고(growth_reco_auto)·제어 완전자동(ctrl_reco_auto)·AI 무제한.

## 네비 잠금(index.html SCREEN_TIER)
g3/g4/g5·f4/f3/f6·c13 = smart, c4 = pro. 그 외 basic.

## 데모 상태
- subscriptions.json: farm_001=pro, 002/003=smart, 004/005=basic. admin 계정은 "admin" 등급(전체 접근).
- C22에서 '미리보기 등급'으로 각 등급 접근을 시연 가능.

## 원칙
- 단일 출처는 `tier_features.json`(54기능·min_tier). 화면·문서·게이팅 모두 이를 참조 — 신규 기능은 여기에만 등록.
