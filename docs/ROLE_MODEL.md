# ROLE_MODEL — 역할별 가입→실행 프로세스 (정직한 MVP)

> 역할 저장: `RegisterRequest.role`(검증 farmer|org|distributor|expert|public) → DB는 안전역할(farmer)만,
> 비즈니스 역할은 `api/data/user_roles.json` 사이드 저장 + `get_user_by_username` 오버레이로 JWT 복원.
> (DB `users_role_check` 제약 때문에 비농가 역할은 직접 저장 불가 → 사이드 파일 우회)

## 역할 → 랜딩 → 1차 기능 → 상태
| 역할 | 랜딩(C0 `_LAND`) | 1차 핵심(구현) | 준비 중(미구현) |
|---|---|---|---|
| farmer 농가 | C1 농장세팅 | 가입→세팅→진단(C17/C19)→운영(G/F)→경영(C5/C14)→출하(C12)→학습(C6/C7) **완결** | — |
| org 생산자조직 | C1→C12 | 농장세팅 + 공동출하 참여 | 조합 거버넌스·조합원·정산 |
| distributor 유통전문가 | C12 공동출하 | 시세·채널비교 조회 + 참여신청 (배너 안내) | 산지수매·가격협상·공급처 |
| expert 재배전문가 | C4 AI진단 | 진단결과+상담예약 (배너 안내) | 전문가 대시보드·담당농가·이력 |
| public 공공기관 | C20 클러스터 | **조회 전용**(공개 `/api/cluster/overview` 폴백) (배너 안내) | 정책·보조금·시뮬레이션 |

## 원칙
- 미구현 영역은 화면에 **'준비 중' 배너**로 정직 표기(가짜 콘솔 금지).
- 백엔드 RBAC는 현재 admin/manager만 강제. 비농가 역할 전용 권한은 단계적 도입.
- 농가 여정 단일 출처: `screens/flow.html` + `api/services/capability_router.py`(4단계).
