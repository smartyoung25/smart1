"""Airflow DAG — 일별 외부 데이터 수집 파이프라인.

Schedule: 매일 01:00 KST (16:00 UTC 전일)
Flow:
  1. fetch_kma_weather   — 기상청 ASOS 전일 관측값 → env_measurements
  2. fetch_kamis_price   — KAMIS 농산물 도매가격 → kamis_price_cache.json
  3. fetch_rda_growth    — 농진청 생육 API (미계약 시 스킵)
  4. validate_data       — 수집 결과 검증 (행 수 · 이상값)
  5. notify_on_failure   — 수집 실패 시 관리자 알림

환경변수:
  KMA_SERVICE_KEY      — 기상청 공공데이터포털 API 키
  KAMIS_CERT_KEY       — KAMIS API 인증 키
  RDA_API_KEY          — 농진청 API 키 (선택)
  DATABASE_URL         — TimescaleDB 연결 URL
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# ---------------------------------------------------------------------------
# Default args
# ---------------------------------------------------------------------------

default_args = {
    "owner":           "smartfarm",
    "retries":         2,
    "retry_delay":     timedelta(minutes=5),
    "email_on_failure": True,
    "email":           ["admin@smartfarm.local"],
}

# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def _get_db_engine():
    import os
    from sqlalchemy import create_engine
    db_url = os.environ.get("DATABASE_URL", "postgresql://smartfarm:smartfarm@db/smartfarm")
    return create_engine(db_url)


def _insert_env_records(engine, rows: list[dict]) -> int:
    """env_measurements 테이블에 벌크 삽입."""
    if not rows:
        return 0
    from sqlalchemy import text
    sql = text(
        """
        INSERT INTO env_measurements
            (time, farm_id, canonical_name, value, source_id, quality_tag, imputed)
        VALUES
            (:time, :farm_id, :canonical_name, :value, :source_id, :quality_tag, :imputed)
        ON CONFLICT (time, farm_id, canonical_name) DO NOTHING
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Task 1: KMA ASOS 기상 데이터 수집
# ---------------------------------------------------------------------------

def fetch_kma_weather(**context):
    """기상청 ASOS 전일 관측값 수집 → env_measurements 적재.

    수집 대상 관측소: FARM_STATION 매핑에 등록된 모든 농가별 ASOS 관측소.
    수집 변수: 평균기온, 평균습도, 최대풍속, 일사량합계.
    """
    import os
    from datetime import date, timedelta
    import requests

    service_key = os.environ.get("KMA_SERVICE_KEY", "")
    if not service_key:
        print("[fetch_kma_weather] KMA_SERVICE_KEY 미설정 — 스킵")
        context["ti"].xcom_push(key="kma_rows", value=0)
        return

    # 전날 날짜
    target_date = (date.today() - timedelta(days=1)).strftime("%Y%m%d")

    # 농가별 ASOS 관측소 매핑 (kma_service.FARM_STATION 미러링)
    FARM_STATIONS: dict[str, int] = {
        "farm_001": 189,   # 창녕(합천)
        "farm_002": 127,   # 충주
        "farm_003": 140,   # 군산
        "farm_004": 137,   # 상주
        "farm_005": 108,   # 서울(기본)
    }

    # 관측소별 수집 (중복 방지)
    stn_to_farms: dict[int, list[str]] = {}
    for fid, stn in FARM_STATIONS.items():
        stn_to_farms.setdefault(stn, []).append(fid)

    BASE_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
    rows: list[dict] = []

    for stn_id, farm_ids in stn_to_farms.items():
        params = {
            "serviceKey":  service_key,
            "pageNo":      1,
            "numOfRows":   1,
            "dataType":    "JSON",
            "dataCd":      "ASOS",
            "dateCd":      "DAY",
            "startDt":     target_date,
            "endDt":       target_date,
            "stnIds":      stn_id,
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = (
                data.get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", [])
            )
            if not items:
                print(f"[fetch_kma_weather] stn={stn_id} 데이터 없음")
                continue

            item = items[0]
            ts_str = f"{item['tm']} 00:00:00+09:00"
            from datetime import datetime
            ts = datetime.fromisoformat(ts_str)

            # 변수 매핑: KMA 필드 → canonical
            kma_map = {
                "avgTa":   ("temp_external",   "TRANSFER"),
                "avgRhm":  ("humidity_ext",    "TRANSFER"),
                "maxWs":   ("wind_speed_ext",  "TRANSFER"),
                "sumGsr":  ("solar_rad",       "TRANSFER"),
                "avgTd":   ("soil_temp",       "TRANSFER"),   # 이슬점 근사 사용
            }

            for kma_key, (canon, qtag) in kma_map.items():
                raw = item.get(kma_key)
                if raw is None or raw == "":
                    continue
                try:
                    val = float(raw)
                except (ValueError, TypeError):
                    continue

                for farm_id in farm_ids:
                    rows.append({
                        "time":           ts,
                        "farm_id":        farm_id,
                        "canonical_name": canon,
                        "value":          val,
                        "source_id":      "kma_asos",
                        "quality_tag":    qtag,
                        "imputed":        False,
                    })

        except Exception as exc:
            print(f"[fetch_kma_weather] stn={stn_id} 오류: {exc}")

    engine = _get_db_engine()
    inserted = _insert_env_records(engine, rows)
    context["ti"].xcom_push(key="kma_rows", value=inserted)
    print(f"[fetch_kma_weather] {target_date} → {inserted}행 삽입 (관측소 {len(stn_to_farms)}개)")


# ---------------------------------------------------------------------------
# Task 2: KAMIS 농산물 도매가격 수집
# ---------------------------------------------------------------------------

def fetch_kamis_price(**context):
    """KAMIS 도매시장 전일 평균 단가 수집 → kamis_price_cache.json 갱신.

    수집 작목: 딸기, 방울토마토, 완숙토마토, 참외, 오이
    """
    import json
    import os
    import requests
    from datetime import date, timedelta
    from pathlib import Path

    cert_key = os.environ.get("KAMIS_CERT_KEY", "")
    if not cert_key:
        print("[fetch_kamis_price] KAMIS_CERT_KEY 미설정 — 스킵")
        context["ti"].xcom_push(key="kamis_items", value=0)
        return

    target_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 농산물 유통정보 도매 API
    BASE_URL = "https://www.kamis.or.kr/service/price/xml.do"

    # 작목별 KAMIS 품목 코드
    CROP_CODES: dict[str, tuple[str, str]] = {
        "딸기":      ("224", "03"),   # 품목코드, 단위
        "방울토마토": ("225", "05"),
        "완숙토마토": ("225", "05"),
        "참외":      ("228", "10"),
        "오이":      ("226", "10"),
    }

    cache: dict[str, float] = {}

    for crop_ko, (item_code, unit_code) in CROP_CODES.items():
        params = {
            "action":       "dailyPriceByCategoryList",
            "p_cert_key":   cert_key,
            "p_cert_id":    "5279",
            "p_returntype": "json",
            "p_startday":   target_date,
            "p_endday":     target_date,
            "p_itemcategorycode": "200",   # 채소류
            "p_itemcode":   item_code,
            "p_kindcode":   unit_code,
            "p_productrankcode": "04",    # 중품
            "p_countrycode": "1101",      # 서울 가락시장
            "p_convert_kg_yn": "Y",       # kg 기준 환산
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", {}).get("item", [])
            if items:
                price_str = items[0].get("price", "0").replace(",", "")
                price = float(price_str) if price_str else 0.0
                if price > 0:
                    cache[crop_ko] = round(price, 0)
                    print(f"[fetch_kamis_price] {crop_ko}: {price:.0f}원/kg")
        except Exception as exc:
            print(f"[fetch_kamis_price] {crop_ko} 오류: {exc}")

    if cache:
        cache_path = Path(__file__).parent.parent.parent / "api" / "data" / "kamis_price_cache.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        # 기존 캐시와 병합 (없는 작목 유지)
        existing: dict = {}
        if cache_path.exists():
            try:
                existing = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        existing.update(cache)
        existing["_updated_at"] = target_date
        cache_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    context["ti"].xcom_push(key="kamis_items", value=len(cache))
    print(f"[fetch_kamis_price] {target_date} → {len(cache)}개 작목 가격 갱신")


# ---------------------------------------------------------------------------
# Task 3: RDA 농진청 생육 API (선택)
# ---------------------------------------------------------------------------

def fetch_rda_growth(**context):
    """농진청 스마트팜 생육 API 수집 → growth_measurements 적재.

    API 계약이 없으면 조용히 스킵한다.
    """
    import os

    rda_key = os.environ.get("RDA_API_KEY", "")
    if not rda_key:
        print("[fetch_rda_growth] RDA_API_KEY 미설정 — 스킵 (API 계약 후 활성화)")
        context["ti"].xcom_push(key="rda_rows", value=0)
        return

    # TODO: RDA API 계약 후 엔드포인트·파라미터 확정
    # 현재는 키 존재 여부만 확인하고 스킵
    print("[fetch_rda_growth] RDA API 연동 예정 — 현재 미구현")
    context["ti"].xcom_push(key="rda_rows", value=0)


# ---------------------------------------------------------------------------
# Task 4: 수집 결과 검증
# ---------------------------------------------------------------------------

def validate_data(**context):
    """수집된 데이터 품질 검증.

    검증 항목:
      - KMA: 수집 행 수 > 0 여부
      - KAMIS: 주요 작목(딸기·방울토마토) 가격 수집 여부
      - env_measurements: 전일 데이터 이상값 (±5σ) 비율 < 5%
    """
    kma_rows    = context["ti"].xcom_pull(key="kma_rows",    task_ids="fetch_kma_weather") or 0
    kamis_items = context["ti"].xcom_pull(key="kamis_items", task_ids="fetch_kamis_price") or 0
    rda_rows    = context["ti"].xcom_pull(key="rda_rows",    task_ids="fetch_rda_growth") or 0

    warnings: list[str] = []

    if kma_rows == 0:
        warnings.append("KMA ASOS 데이터 수집 0행 — 기상청 API 점검 필요")

    if kamis_items == 0:
        warnings.append("KAMIS 가격 수집 0건 — API 키 또는 네트워크 점검 필요")
    elif kamis_items < 3:
        warnings.append(f"KAMIS 가격 수집 {kamis_items}건 — 일부 작목 누락 가능")

    # DB 이상값 비율 검증
    try:
        from datetime import date, timedelta
        engine = _get_db_engine()
        from sqlalchemy import text
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with engine.connect() as conn:
            result = conn.execute(text(
                f"""
                SELECT
                    canonical_name,
                    COUNT(*) FILTER (WHERE quality_tag = 'FINETUNED') AS total,
                    COUNT(*) FILTER (WHERE ABS(value - avg_val) > 5 * std_val) AS outliers
                FROM env_measurements
                CROSS JOIN LATERAL (
                    SELECT AVG(value) AS avg_val, STDDEV(value) AS std_val
                    FROM env_measurements e2
                    WHERE e2.canonical_name = env_measurements.canonical_name
                    AND e2.time >= NOW() - INTERVAL '30 days'
                ) stats
                WHERE time::date = '{yesterday}'
                GROUP BY canonical_name
                HAVING COUNT(*) > 10
                """
            )).fetchall()

            for row in result:
                if row[1] > 0:
                    ratio = row[2] / row[1]
                    if ratio > 0.05:
                        warnings.append(
                            f"이상값 비율 {ratio:.1%} ({row[0]}): {row[2]}/{row[1]}행"
                        )
    except Exception as exc:
        print(f"[validate_data] DB 이상값 검증 실패: {exc}")

    context["ti"].xcom_push(key="validation_warnings", value=warnings)

    if warnings:
        print(f"[validate_data] 경고 {len(warnings)}건:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print(f"[validate_data] 검증 통과 — KMA {kma_rows}행, KAMIS {kamis_items}건, RDA {rda_rows}행")


# ---------------------------------------------------------------------------
# Task 5: 실패 알림
# ---------------------------------------------------------------------------

def notify_on_failure(**context):
    """검증 경고 또는 태스크 실패 시 관리자에게 알림 발송.

    운영 환경에서는 Slack Webhook 또는 이메일 발송.
    """
    warnings = context["ti"].xcom_pull(key="validation_warnings", task_ids="validate_data") or []

    if not warnings:
        print("[notify_on_failure] 알림 없음 — 정상 완료")
        return

    msg = "\n".join(f"- {w}" for w in warnings)
    print(f"[notify_on_failure] 알림 발송:\n{msg}")

    # Slack Webhook (SLACK_WEBHOOK_URL 설정 시 활성화)
    import os
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if webhook_url:
        try:
            import requests
            payload = {
                "text": f"🌿 스마트팜 데이터 수집 경고\n{msg}",
                "username": "SmartFarm DAG",
            }
            requests.post(webhook_url, json=payload, timeout=5)
            print("[notify_on_failure] Slack 알림 발송 완료")
        except Exception as exc:
            print(f"[notify_on_failure] Slack 발송 실패: {exc}")


# ---------------------------------------------------------------------------
# DAG 정의
# ---------------------------------------------------------------------------

with DAG(
    dag_id="smartfarm_data_collection",
    default_args=default_args,
    description="일별 외부 데이터 수집 (KMA / KAMIS / RDA)",
    schedule_interval="0 16 * * *",   # 01:00 KST = 16:00 UTC 전일
    start_date=datetime(2026, 5, 1),
    catchup=False,
    tags=["smartfarm", "data_collection"],
) as dag:

    t_kma    = PythonOperator(task_id="fetch_kma_weather", python_callable=fetch_kma_weather)
    t_kamis  = PythonOperator(task_id="fetch_kamis_price", python_callable=fetch_kamis_price)
    t_rda    = PythonOperator(task_id="fetch_rda_growth",  python_callable=fetch_rda_growth)
    t_valid  = PythonOperator(task_id="validate_data",     python_callable=validate_data)
    t_notify = PythonOperator(task_id="notify_on_failure", python_callable=notify_on_failure)

    # KMA, KAMIS, RDA 병렬 수집 → 검증 → 알림
    [t_kma, t_kamis, t_rda] >> t_valid >> t_notify
