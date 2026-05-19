"""관리자 계정 비밀번호 초기화 스크립트.

.env의 ADMIN_PASSWORD를 bcrypt 해시로 DB에 업데이트합니다.

사용법:
    python scripts/init_admin_password.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    db_url = os.environ.get("DATABASE_URL", "").strip()

    if not admin_password:
        print("오류: .env에 ADMIN_PASSWORD가 설정되지 않았습니다.")
        sys.exit(1)
    if admin_password == "change_me_strong_password":
        print("경고: 기본 비밀번호를 그대로 사용하고 있습니다. .env를 수정하세요.")
        sys.exit(1)
    if not db_url:
        print("오류: .env에 DATABASE_URL이 설정되지 않았습니다.")
        sys.exit(1)

    try:
        import bcrypt
    except ImportError:
        print("오류: bcrypt 패키지가 필요합니다. pip install bcrypt")
        sys.exit(1)

    hashed = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()

    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET hashed_password = %s WHERE username = 'admin'",
            (hashed,)
        )
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO users (username, hashed_password, role) VALUES ('admin', %s, 'admin')",
                (hashed,)
            )
        conn.commit()
        cur.close()
        conn.close()
        print("admin 비밀번호가 성공적으로 설정되었습니다.")
    except Exception as e:
        print(f"DB 오류: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
