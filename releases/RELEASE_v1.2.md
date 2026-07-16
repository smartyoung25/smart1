# KAASA SmartOS v1.2 — 릴리스 노트

> 패키지: KAASA_SmartOS_v1.2.zip · 2026-06-08 · Farmingsight
> 진입: /intro (시스템 소개) → 시작하기/둘러보기

## v1.1 → v1.2 (압축·보강)
- **보안 보강**: JWT secret 강력 랜덤화 · 공개 데모 읽기전용 모드(PUBLIC_DEMO: 쓰기·관리자 403)
- **배포 보강**: Cloudflare Tunnel 키트(공인 HTTPS, 무 서버) · demo_live.bat(원클릭 공개) · run_api_resilient.bat(자동재기동)
- **운영 보강**: .env.example(환경 표준화) · seed_demo.py(데모 시딩) · smoke_test.py(회귀 자동검증)
- **UX 보강**: 데모 모드 쓰기 시 '읽기 전용' 안내 처리

## 통합 패키지 구성
- frontend: index + screens(34) + components(9)
- config: equipment_schema·tier_features·.env.example
- deploy: DEPLOY.md·docker-compose·nginx·cloudflare 키트·자동재기동
- scripts: seed_demo·smoke_test
- docs: 모델고도화·사업계획정합·기자재통합·UI벤치마크

## 보안 (공개 전 필수)
JWT_SECRET_KEY 랜덤화 · ADMIN_PASSWORD 변경 · ALLOWED_ORIGINS 제한 · 공개시 PUBLIC_DEMO=1

## 성능
intro/smartos FCP ~450ms·14KB · c3_home 480ms·64KB → LCP<3s

## 검수
smoke_test.py 전항목 통과: 백엔드10·쓰기4·37화면 콘솔0·35링크 200
