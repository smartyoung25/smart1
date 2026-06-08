@echo off
REM ===== KAASA SmartOS — Cloudflare Tunnel 공개 배포 =====
REM 사전: Cloudflare 계정 + 도메인이 Cloudflare에 등록되어 있어야 함
echo [1] cloudflared 설치
winget install --id Cloudflare.cloudflared -e
echo [2] 로그인 (브라우저에서 도메인 인증)
cloudflared tunnel login
echo [3] 터널 생성
cloudflared tunnel create kaasa-smartos
echo   ^^ 출력된 Tunnel ID 와 json 경로를 config.yml 에 반영하세요.
echo [4] DNS 라우팅 (your.domain.com 을 실도메인으로)
echo   cloudflared tunnel route dns kaasa-smartos your.domain.com
echo [5] 실행 (API 가 :8000 에서 돌고 있어야 함)
echo   cloudflared tunnel --config deploy\cloudflare\config.yml run kaasa-smartos
echo.
echo 완료 후 https://your.domain.com/intro 로 공개 HTTPS 접속됩니다.
