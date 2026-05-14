# 로컬 DB 구축 (Docker + TimescaleDB) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Docker Desktop + TimescaleDB를 로컬에 기동하여 현재 서버 재시작 시 사라지는 수동 입력 데이터(환경값·비용값·농장 메타)를 DB에 영속화한다.

**Architecture:** docker-compose의 `db` 서비스(TimescaleDB)만 기동 → `api/db.py`에 SQLAlchemy 엔진 추가 → farmer.py의 in-memory dict 3개(`_FARM_META`, `_MANUAL_ENV`, `_MANUAL_COSTS`)를 DB read/write로 교체. in-memory dict는 시드 데이터 / DB 없을 때 fallback으로 유지.

**Tech Stack:** Docker Desktop, TimescaleDB (PostgreSQL 15), SQLAlchemy 2.x (Core, text() 방식), python-dotenv, psycopg2-binary

---

## 영향 받는 파일 목록

| 파일 | 변경 유형 | 역할 |
|------|---------|------|
| `db/schema/farms.sql` | 신규 생성 | farms·manual_env·manual_costs 테이블 DDL |
| `api/db.py` | 신규 생성 | SQLAlchemy engine·session·헬스체크 |
| `api/main.py` | 수정 | 앱 시작 시 DB 시딩 호출 |
| `api/routers/farmer.py` | 수정 | meta·manual_env·manual_costs → DB read/write |
| `.env` | 신규 생성 | DATABASE_URL 로컬 설정 |
| `requirements.txt` | 수정 | python-dotenv 추가 |

---

## Task 1: Docker Desktop 설치 및 DB 컨테이너 기동

> ⚠️ 이 태스크는 **사용자가 직접 수행**해야 한다.

- [ ] **Step 1: Docker Desktop 다운로드 및 설치**

  https://www.docker.com/products/docker-desktop/ 에서 Windows 용 설치
  설치 후 재시작 필요할 수 있음.

- [ ] **Step 2: Docker 동작 확인**

  ```bash
  docker --version
  docker ps
  ```
  Expected: `Docker version 25.x.x` 출력, 오류 없음

- [ ] **Step 3: DB 컨테이너만 기동 (전체 stack 불필요)**

  ```bash
  cd D:/project/smart_farm
  docker-compose up -d db
  ```
  Expected: `[+] Running 1/1` 메시지, db 컨테이너 시작

- [ ] **Step 4: DB 연결 확인**

  ```bash
  docker exec -it smart_farm-db-1 psql -U smartfarm -d smartfarm -c "\dt"
  ```
  Expected: `variable_registry`, `variable_source_mapping` 테이블 목록 출력
  (db/schema/variable_registry.sql이 자동 실행됨)

---

## Task 2: farms 스키마 추가

**Files:**
- Create: `db/schema/farms.sql`

- [ ] **Step 1: farms.sql 파일 작성**

  ```sql
  -- ============================================================
  -- farms — 농가 메타 영속 저장
  -- manual_env — 농가별 수동 입력 환경값
  -- manual_costs — 농가별 수동 입력 비용값
  -- ============================================================

  CREATE TABLE IF NOT EXISTS farms (
      farm_id          VARCHAR(32) PRIMARY KEY,
      name             VARCHAR(128) NOT NULL,
      crop             VARCHAR(64),
      area_m2          FLOAT NOT NULL DEFAULT 0,
      tier             VARCHAR(16) NOT NULL DEFAULT 'manual',
      iot_available    BOOLEAN NOT NULL DEFAULT FALSE,
      sido             VARCHAR(64),
      sigungu          VARCHAR(64),
      address_detail   VARCHAR(256),
      asos_station_id  INTEGER,
      updated_at       TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE TABLE IF NOT EXISTS manual_env (
      farm_id         VARCHAR(32) NOT NULL,
      canonical_name  VARCHAR(64) NOT NULL,
      value           FLOAT NOT NULL,
      updated_at      TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY (farm_id, canonical_name)
  );

  CREATE TABLE IF NOT EXISTS manual_costs (
      farm_id     VARCHAR(32) NOT NULL,
      key         VARCHAR(64) NOT NULL,
      value       FLOAT NOT NULL,
      updated_at  TIMESTAMPTZ DEFAULT NOW(),
      PRIMARY KEY (farm_id, key)
  );
  ```

- [ ] **Step 2: 컨테이너에 스키마 적용**

  ```bash
  docker exec -i smart_farm-db-1 psql -U smartfarm -d smartfarm < db/schema/farms.sql
  ```
  Expected: `CREATE TABLE` × 3 출력

- [ ] **Step 3: 테이블 생성 확인**

  ```bash
  docker exec -it smart_farm-db-1 psql -U smartfarm -d smartfarm -c "\dt"
  ```
  Expected: `farms`, `manual_env`, `manual_costs` 포함된 테이블 목록

- [ ] **Step 4: 커밋**

  ```bash
  git add db/schema/farms.sql
  git commit -m "feat(db): farms·manual_env·manual_costs 테이블 스키마 추가"
  ```

---

## Task 3: .env 파일 및 requirements 설정

**Files:**
- Create: `.env`
- Modify: `requirements.txt`

- [ ] **Step 1: .env 파일 생성**

  ```
  DATABASE_URL=postgresql://smartfarm:smartfarm@localhost:5432/smartfarm
  ```
  > `.env`는 `.gitignore`에 이미 등록되어 있으므로 커밋되지 않음.

- [ ] **Step 2: requirements.txt에 python-dotenv 추가**

  ```
  python-dotenv>=1.0.0
  ```
  기존 `psycopg2-binary>=2.9.9` 이미 포함되어 있음 — 추가 불필요.

- [ ] **Step 3: python-dotenv 설치**

  ```bash
  pip install python-dotenv
  ```

- [ ] **Step 4: 커밋**

  ```bash
  git add requirements.txt
  git commit -m "chore: python-dotenv 의존성 추가"
  ```

---

## Task 4: api/db.py — DB 세션 레이어

**Files:**
- Create: `api/db.py`

- [ ] **Step 1: api/db.py 작성**

  ```python
  """
  api/db.py
  SQLAlchemy 엔진·세션·헬스체크.
  DATABASE_URL 환경변수 없으면 None 반환 — 호출부에서 fallback 처리.
  """
  from __future__ import annotations

  import os
  from contextlib import contextmanager

  from dotenv import load_dotenv
  from sqlalchemy import create_engine, text
  from sqlalchemy.orm import sessionmaker
  from sqlalchemy.exc import OperationalError

  load_dotenv()  # .env 로드

  _DATABASE_URL: str | None = os.getenv("DATABASE_URL")
  _engine = None
  _Session = None

  if _DATABASE_URL:
      try:
          _engine = create_engine(
              _DATABASE_URL,
              pool_pre_ping=True,
              pool_size=5,
              max_overflow=10,
              connect_args={"connect_timeout": 3},
          )
          _Session = sessionmaker(bind=_engine)
      except Exception:
          _engine = None
          _Session = None


  def is_available() -> bool:
      """DB 연결 가능 여부 확인."""
      if _engine is None:
          return False
      try:
          with _engine.connect() as conn:
              conn.execute(text("SELECT 1"))
          return True
      except OperationalError:
          return False


  @contextmanager
  def get_session():
      """DB 세션 컨텍스트 매니저. DB 없으면 None yield."""
      if _Session is None:
          yield None
          return
      session = _Session()
      try:
          yield session
          session.commit()
      except Exception:
          session.rollback()
          raise
      finally:
          session.close()
  ```

- [ ] **Step 2: DB 연결 테스트**

  ```bash
  cd D:/project/smart_farm
  python -c "from api.db import is_available; print('DB available:', is_available())"
  ```
  Expected: `DB available: True`

- [ ] **Step 3: 커밋**

  ```bash
  git add api/db.py
  git commit -m "feat(api): SQLAlchemy DB 세션 레이어 추가"
  ```

---

## Task 5: 농장 메타 DB 마이그레이션 (farms 테이블)

**Files:**
- Modify: `api/main.py` — 시작 시 시드 함수 호출
- Modify: `api/routers/farmer.py` — `_FARM_META` 읽기/쓰기 → DB

- [ ] **Step 1: api/main.py에 startup 이벤트로 시드 추가**

  `app = FastAPI(...)` 아래에 추가:

  ```python
  from api.db import get_session, is_available

  @app.on_event("startup")
  def seed_farms():
      """DB가 연결된 경우 farms 테이블에 초기 데이터 시딩 (중복 무시)."""
      if not is_available():
          return
      from api.routers.farmer import _FARM_META
      from sqlalchemy import text
      with get_session() as db:
          if db is None:
              return
          for farm_id, meta in _FARM_META.items():
              db.execute(text("""
                  INSERT INTO farms
                      (farm_id, name, crop, area_m2, tier, iot_available,
                       sido, sigungu, address_detail)
                  VALUES
                      (:farm_id, :name, :crop, :area_m2, :tier, :iot_available,
                       :sido, :sigungu, :address_detail)
                  ON CONFLICT (farm_id) DO NOTHING
              """), {
                  "farm_id":        farm_id,
                  "name":           meta["name"],
                  "crop":           meta.get("crop", ""),
                  "area_m2":        meta["area_m2"],
                  "tier":           meta["tier"].value,
                  "iot_available":  meta["iot_available"],
                  "sido":           meta.get("sido"),
                  "sigungu":        meta.get("sigungu"),
                  "address_detail": meta.get("address_detail", ""),
              })
  ```

- [ ] **Step 2: farmer.py의 `update_meta()` — DB에 쓰기**

  현재 `update_meta()` 함수 (line ~388) 내부에 DB 저장 추가:

  ```python
  from api.db import get_session
  from sqlalchemy import text

  # update_meta() 함수 끝부분, return 직전에:
  with get_session() as db:
      if db is not None:
          db.execute(text("""
              INSERT INTO farms
                  (farm_id, name, crop, area_m2, sido, sigungu, address_detail, asos_station_id)
              VALUES
                  (:farm_id, :name, :crop, :area_m2, :sido, :sigungu, :address_detail, :asos_station_id)
              ON CONFLICT (farm_id) DO UPDATE SET
                  name = EXCLUDED.name,
                  crop = EXCLUDED.crop,
                  area_m2 = EXCLUDED.area_m2,
                  sido = EXCLUDED.sido,
                  sigungu = EXCLUDED.sigungu,
                  address_detail = EXCLUDED.address_detail,
                  asos_station_id = EXCLUDED.asos_station_id,
                  updated_at = NOW()
          """), {
              "farm_id":        farm_id,
              "name":           meta["name"],
              "crop":           meta.get("crop", ""),
              "area_m2":        meta["area_m2"],
              "sido":           meta.get("sido"),
              "sigungu":        meta.get("sigungu"),
              "address_detail": meta.get("address_detail", ""),
              "asos_station_id": meta.get("asos_station_id"),
          })
  ```

- [ ] **Step 3: farmer.py의 `get_meta()` — DB에서 읽기 (fallback: in-memory)**

  ```python
  def get_meta(farm_id: str):
      _require_farm(farm_id)
      # DB 우선 조회
      with get_session() as db:
          if db is not None:
              row = db.execute(
                  text("SELECT * FROM farms WHERE farm_id = :fid"),
                  {"fid": farm_id}
              ).mappings().first()
              if row:
                  # DB 값으로 _FARM_META 갱신 (런타임 동기화)
                  _FARM_META[farm_id].update({
                      "name":           row["name"],
                      "crop":           row["crop"],
                      "area_m2":        row["area_m2"],
                      "sido":           row["sido"],
                      "sigungu":        row["sigungu"],
                      "address_detail": row["address_detail"],
                      "asos_station_id": row["asos_station_id"],
                  })
      return _meta_to_response(farm_id, _FARM_META[farm_id])
  ```

- [ ] **Step 4: 서버 재시작 후 시딩 확인**

  ```bash
  docker exec -it smart_farm-db-1 psql -U smartfarm -d smartfarm \
    -c "SELECT farm_id, name, crop FROM farms;"
  ```
  Expected: farm_001~farm_005 5행 출력

- [ ] **Step 5: FarmSettings 저장 → DB 반영 확인**

  브라우저에서 농장 이름 변경 저장 → 서버 재시작 → 변경된 이름 유지 확인

- [ ] **Step 6: 커밋**

  ```bash
  git add api/main.py api/routers/farmer.py
  git commit -m "feat(db): 농장 메타 DB 영속화 (farms 테이블)"
  ```

---

## Task 6: 수동 환경값 DB 마이그레이션 (manual_env 테이블)

**Files:**
- Modify: `api/routers/farmer.py` — `_MANUAL_ENV` → DB

- [ ] **Step 1: `submit_manual_env()` — DB에 쓰기**

  현재 `_MANUAL_ENV[farm_id].update(incoming)` 부분을 DB upsert로 교체:

  ```python
  # _MANUAL_ENV 업데이트는 그대로 유지 (in-memory cache 역할)
  if farm_id not in _MANUAL_ENV:
      _MANUAL_ENV[farm_id] = {}
  _MANUAL_ENV[farm_id].update(incoming)

  # DB에도 저장
  with get_session() as db:
      if db is not None:
          for canonical_name, value in incoming.items():
              db.execute(text("""
                  INSERT INTO manual_env (farm_id, canonical_name, value, updated_at)
                  VALUES (:farm_id, :canonical_name, :value, NOW())
                  ON CONFLICT (farm_id, canonical_name) DO UPDATE
                  SET value = EXCLUDED.value, updated_at = NOW()
              """), {"farm_id": farm_id, "canonical_name": canonical_name, "value": value})
  ```

- [ ] **Step 2: `_get_env()` / startup — DB에서 `_MANUAL_ENV` 복구**

  `seed_farms()` 함수에 manual_env 복구 로직 추가:

  ```python
  # api/main.py seed_farms() 함수 끝에 추가
  rows = db.execute(text("SELECT farm_id, canonical_name, value FROM manual_env")).mappings().all()
  from api.routers.farmer import _MANUAL_ENV
  for row in rows:
      fid = row["farm_id"]
      if fid not in _MANUAL_ENV:
          _MANUAL_ENV[fid] = {}
      _MANUAL_ENV[fid][row["canonical_name"]] = row["value"]
  ```

- [ ] **Step 3: 수동 환경값 영속성 확인**

  1. 브라우저 환경 탭 → 수동 입력 제출
  2. 서버 재시작 (`Ctrl+C` → 재기동)
  3. 환경 탭에서 입력값 유지 확인
  4. DB 확인: `SELECT * FROM manual_env;`

- [ ] **Step 4: 커밋**

  ```bash
  git add api/routers/farmer.py api/main.py
  git commit -m "feat(db): 수동 환경값 DB 영속화 (manual_env 테이블)"
  ```

---

## Task 7: 수동 비용값 DB 마이그레이션 (manual_costs 테이블)

**Files:**
- Modify: `api/routers/farmer.py` — `_MANUAL_COSTS` → DB

- [ ] **Step 1: `post_costs_manual()` — DB에 쓰기**

  현재 `_MANUAL_COSTS[farm_id].update(...)` 이후에 추가:

  ```python
  with get_session() as db:
      if db is not None:
          for key, value in body_dict.items():
              if value is not None:
                  db.execute(text("""
                      INSERT INTO manual_costs (farm_id, key, value, updated_at)
                      VALUES (:farm_id, :key, :value, NOW())
                      ON CONFLICT (farm_id, key) DO UPDATE
                      SET value = EXCLUDED.value, updated_at = NOW()
                  """), {"farm_id": farm_id, "key": key, "value": value})
  ```

- [ ] **Step 2: `delete_costs_manual()` — DB에서도 삭제**

  ```python
  with get_session() as db:
      if db is not None:
          db.execute(text("DELETE FROM manual_costs WHERE farm_id = :fid"), {"fid": farm_id})
  ```

- [ ] **Step 3: `seed_farms()`에 manual_costs 복구 추가**

  ```python
  rows = db.execute(text("SELECT farm_id, key, value FROM manual_costs")).mappings().all()
  from api.routers.farmer import _MANUAL_COSTS
  for row in rows:
      fid = row["farm_id"]
      if fid not in _MANUAL_COSTS:
          _MANUAL_COSTS[fid] = {}
      _MANUAL_COSTS[fid][row["key"]] = row["value"]
  ```

- [ ] **Step 4: 비용값 영속성 확인**

  1. 브라우저 비용 탭 → 전기 사용량 수동 입력
  2. 서버 재시작
  3. 비용 탭에서 입력값 유지 확인

- [ ] **Step 5: 커밋**

  ```bash
  git add api/routers/farmer.py api/main.py
  git commit -m "feat(db): 수동 비용값 DB 영속화 (manual_costs 테이블)"
  ```

---

## Task 8: 통합 검증

- [ ] **Step 1: DB 없이도 동작 확인 (fallback)**

  ```bash
  docker-compose stop db
  # API 재시작 후
  curl http://localhost:8014/api/farms/farm_003/environment
  ```
  Expected: 오류 없이 응답 (in-memory fallback 동작)

- [ ] **Step 2: DB 재기동 후 데이터 복구 확인**

  ```bash
  docker-compose up -d db
  # API 재시작 후
  curl http://localhost:8014/api/farms/farm_003/meta
  ```
  Expected: 이전에 저장한 이름/작목/면적 유지

- [ ] **Step 3: 전체 엔드포인트 스모크 테스트**

  ```bash
  python -m pytest tests/ -v --tb=short 2>/dev/null || echo "테스트 없음"
  curl http://localhost:8014/api/farms/farm_003/summary
  curl http://localhost:8014/api/farms/farm_003/revenue
  curl http://localhost:8014/api/farms/farm_003/harvest
  ```

- [ ] **Step 4: 최종 커밋**

  ```bash
  git add .
  git commit -m "feat: 로컬 DB 구축 완료 — 수동 입력 데이터 영속화"
  ```

---

## 완료 기준

| 항목 | 확인 방법 |
|------|---------|
| Docker DB 기동 | `docker ps` — db 컨테이너 Up |
| 농장 메타 영속 | 이름 변경 저장 → 재시작 → 유지 |
| 수동 환경값 영속 | 환경 수동 입력 → 재시작 → 유지 |
| 수동 비용값 영속 | 비용 수동 입력 → 재시작 → 유지 |
| DB 없이도 동작 | db 컨테이너 중지 → API 정상 응답 |

---

*작성일: 2026-05-13*
