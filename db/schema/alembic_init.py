"""Alembic 초기화 스크립트.

실행:
    cd D:/project/smart_farm
    alembic init db/migrations
    # alembic.ini의 sqlalchemy.url을 DATABASE_URL로 교체
    alembic revision --autogenerate -m "initial schema"
    alembic upgrade head

TimescaleDB hypertable 활성화는 variable_registry.sql의 주석을 해제:
    SELECT create_hypertable('env_measurements', 'time', if_not_exists => TRUE);
"""
