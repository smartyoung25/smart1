-- ============================================================
-- 관리자 비밀번호 초기화 스크립트
-- docker-compose 실행 후 아래 명령으로 실행:
--   docker-compose exec db psql -U smartfarm -d smartfarm -f /docker-entrypoint-initdb.d/init_admin.sql
--
-- 또는 Python에서:
--   python scripts/init_admin_password.py
-- ============================================================

-- ADMIN_PASSWORD 환경변수로 교체하는 방법:
-- 1. .env 파일에 ADMIN_PASSWORD=your_password 설정
-- 2. scripts/init_admin_password.py 실행

-- 비밀번호를 직접 bcrypt 해시로 설정하려면 아래 UPDATE 실행:
-- UPDATE users SET hashed_password = '<bcrypt_hash>' WHERE username = 'admin';
