"""데이터 수집 API 라우터.

농가·스마트팜에서 실측한 생육값(주간) / 수확량(시즌)을 수신하여
PostgreSQL → JSON 파일 순서로 저장하고,
임계치(수확 10건 / 생육 30건) 도달 시 M1/M2 자동 재학습을 트리거합니다.

엔드포인트:
    POST   /api/data/growth          — 주간 생육 측정값 수신
    POST   /api/data/harvest         — 시즌 수확량 실측값 수신
    GET    /api/data/status          — 전체 수집 현황
    GET    /api/data/status/{farm_id} — 농장별 수집 현황
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from api.middleware.auth import require_auth
from api.schemas.data_collection import (
    GrowthRecord,
    GrowthRecordResponse,
    ExpertLabelRequest,
    HarvestRecord,
    HarvestRecordResponse,
    DataStatusResponse,
    DataCountItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["data-collection"])

# 공개 데모 모드 — 재학습 subprocess 실행 차단(시뮬레이션화)에 사용
_PUBLIC_DEMO = os.environ.get("PUBLIC_DEMO", "").lower() in ("1", "true", "yes")

# 소유권 검증 — 토큰 농장과 대상 farm_id 일치 요구. admin/manager/demo는 전체 허용.
#   (data_collection은 farmer 라우터 밖이라 _verify_farm_ownership가 적용되지 않으므로
#    여기서 동형 검사를 수행한다.)
def _require_owner(user: dict, farm_id: str) -> None:
    role = (user or {}).get("role", "")
    if role in ("admin", "manager", "superadmin", "demo"):
        return
    token_farm = (user or {}).get("farm_id", "")
    if (not token_farm) or token_farm != farm_id:
        raise HTTPException(status_code=403, detail="해당 농가에 대한 접근 권한이 없습니다.")

# ── 저장 경로 (JSON 파일 폴백) ─────────────────────────────────────────────────
_DATA_DIR = Path("data/collected")
_GROWTH_DIR  = _DATA_DIR / "growth"
_HARVEST_DIR = _DATA_DIR / "harvest"
_RETRAIN_STATE = _DATA_DIR / "retrain_state.json"

# ── 재학습 임계치 ─────────────────────────────────────────────────────────────
_THRESHOLD_HARVEST = int(os.environ.get("RETRAIN_THRESHOLD_HARVEST", "10"))
_THRESHOLD_GROWTH  = int(os.environ.get("RETRAIN_THRESHOLD_GROWTH",  "30"))


# ── 시즌 평균 환경값 자동 계산 ─────────────────────────────────────────────────

def _auto_season_env(farm_id: str, start_date: str, end_date: str
                     ) -> tuple[Optional[float], Optional[float]]:
    """PostgreSQL sensor_data에서 정식일~수확일 기간의 평균 온도·습도를 조회.

    Returns:
        (avg_temp_c, avg_humidity_pct) — DB 조회 실패 또는 데이터 없으면 (None, None)
    """
    try:
        from api.services.persistence import _get_engine
        from sqlalchemy import text
        engine = _get_engine()
        if engine is None:
            return None, None

        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        AVG(CAST(payload->>'temp_internal' AS FLOAT)) AS avg_temp,
                        AVG(CAST(payload->>'humidity_int'  AS FLOAT)) AS avg_humi
                    FROM sensor_data
                    WHERE farm_id = :farm_id
                      AND recorded_at::date BETWEEN :start AND :end
                      AND payload->>'temp_internal' IS NOT NULL
                """),
                {"farm_id": farm_id, "start": start_date, "end": end_date},
            ).fetchone()

        if row is None or row[0] is None:
            return None, None
        avg_temp = round(float(row[0]), 1) if row[0] is not None else None
        avg_humi = round(float(row[1]), 1) if row[1] is not None else None
        return avg_temp, avg_humi

    except Exception as e:
        logger.debug("[data_collection] 시즌 환경값 자동 계산 실패: %s", e)
        return None, None

# ── 인메모리 카운터 (서버 재시작 시 파일에서 복원) ──────────────────────────────
_counts: dict[str, dict[str, int]] = {}   # crop_ko → {"growth": n, "harvest": n}
_last_retrain: dict[str, str] = {}         # crop_ko → ISO timestamp


def _ensure_dirs():
    _GROWTH_DIR.mkdir(parents=True, exist_ok=True)
    _HARVEST_DIR.mkdir(parents=True, exist_ok=True)


def _load_retrain_state():
    global _last_retrain
    if _RETRAIN_STATE.exists():
        try:
            state = json.loads(_RETRAIN_STATE.read_text(encoding="utf-8"))
            _last_retrain = state.get("last_retrain", {})
        except Exception:
            pass


def _save_retrain_state():
    try:
        _RETRAIN_STATE.parent.mkdir(parents=True, exist_ok=True)
        _RETRAIN_STATE.write_text(
            json.dumps({"last_retrain": _last_retrain}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("[data_collection] retrain 상태 저장 실패: %s", e)


def _count_files(directory: Path, crop_ko: str) -> int:
    """특정 작목의 저장된 레코드 파일 수 카운트."""
    if not directory.exists():
        return 0
    safe_crop = crop_ko.replace("/", "_").replace("\\", "_")
    return len(list(directory.glob(f"{safe_crop}_*.json")))


def _get_counts(crop_ko: str) -> dict[str, int]:
    if crop_ko not in _counts:
        _counts[crop_ko] = {
            "growth":  _count_files(_GROWTH_DIR,  crop_ko),
            "harvest": _count_files(_HARVEST_DIR, crop_ko),
        }
    return _counts[crop_ko]


# ── DB 저장 (persistence 패턴과 동일) ────────────────────────────────────────

_ALLOWED_TABLES = {"growth_records", "harvest_records"}


def _save_to_db(table: str, record: dict) -> Optional[str]:
    """PostgreSQL에 레코드 저장. 실패 시 None 반환 (JSON 폴백 사용)."""
    if table not in _ALLOWED_TABLES:
        logger.error("[data_collection] 허용되지 않은 테이블: %s", table)
        return None
    try:
        from api.services.persistence import _get_engine
        engine = _get_engine()
        if engine is None:
            return None
        from sqlalchemy import text
        rec_id = record.get("id", str(uuid.uuid4()))
        with engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO {table}
                        (id, farm_id, crop_ko, recorded_at, payload)
                    VALUES
                        (:id, :farm_id, :crop_ko, :recorded_at, :payload::jsonb)
                    ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id":          rec_id,
                    "farm_id":     record["farm_id"],
                    "crop_ko":     record["crop_ko"],
                    "recorded_at": record["recorded_at"],
                    "payload":     json.dumps(record, ensure_ascii=False, default=str),
                },
            )
        return rec_id
    except Exception as e:
        logger.debug("[data_collection] DB 저장 실패 (JSON 폴백): %s", e)
        return None


def _save_to_json(directory: Path, crop_ko: str, record: dict) -> str:
    """JSON 파일로 레코드 저장. 파일명: {crop_ko}_{uuid}.json"""
    _ensure_dirs()
    rec_id = record.get("id", str(uuid.uuid4()))
    safe_crop = crop_ko.replace("/", "_").replace("\\", "_")
    fpath = directory / f"{safe_crop}_{rec_id}.json"
    fpath.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return rec_id


# ── VPD 자동 계산 ─────────────────────────────────────────────────────────────

def _calc_vpd(temp_c: Optional[float], humidity_pct: Optional[float]) -> Optional[float]:
    """온도·습도 → VPD (kPa) 계산. Magnus 공식 기반."""
    if temp_c is None or humidity_pct is None:
        return None
    import math
    es = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))   # 포화수증기압
    ea = es * (humidity_pct / 100.0)                              # 실제수증기압
    return round(max(0.0, es - ea), 4)


# ── 자동 재학습 트리거 ────────────────────────────────────────────────────────

def _trigger_retrain(crop_ko: str, mode: str = "m2") -> str:
    """백그라운드에서 해당 작목 M1/M2 재학습을 실행합니다.

    Args:
        crop_ko: 작목 한국어명 (예: 딸기)
        mode: "m1" | "m2" | "both"

    Returns:
        결과 메시지 (한국어)
    """
    import subprocess, sys
    from models.crop_config import CROP_CONFIGS

    cfg = CROP_CONFIGS.get(crop_ko)
    if cfg is None:
        logger.warning("[retrain] 알 수 없는 작목: %s", crop_ko)
        return f"작목 '{crop_ko}'를 찾을 수 없습니다."

    root = Path(__file__).parent.parent.parent
    python = sys.executable

    results = []
    try:
        if mode in ("m1", "both"):
            logger.info("[retrain] M1 재학습 시작: %s", crop_ko)
            r1 = subprocess.run(
                [python, str(root / "scripts" / "train_stage1_growth.py"),
                 "--crop", crop_ko, "--no-cache-build"],
                capture_output=True, text=True, timeout=600, cwd=str(root),
            )
            if r1.returncode == 0:
                results.append(f"M1({crop_ko}) 재학습 완료")
                logger.info("[retrain] M1 완료: %s", crop_ko)
            else:
                results.append(f"M1({crop_ko}) 재학습 실패: {r1.stderr[-200:]}")
                logger.error("[retrain] M1 실패: %s\n%s", crop_ko, r1.stderr[-500:])

        if mode in ("m2", "both"):
            logger.info("[retrain] M2 재학습 시작: %s", crop_ko)
            r2 = subprocess.run(
                [python, str(root / "scripts" / "train_stage2_yield.py"),
                 "--crop", crop_ko, "--no-cache-build"],
                capture_output=True, text=True, timeout=600, cwd=str(root),
            )
            if r2.returncode == 0:
                results.append(f"M2({crop_ko}) 재학습 완료")
                logger.info("[retrain] M2 완료: %s", crop_ko)
            else:
                results.append(f"M2({crop_ko}) 재학습 실패: {r2.stderr[-200:]}")
                logger.error("[retrain] M2 실패: %s\n%s", crop_ko, r2.stderr[-500:])

        _last_retrain[crop_ko] = datetime.now(timezone.utc).isoformat()
        _save_retrain_state()

    except subprocess.TimeoutExpired:
        results.append(f"{crop_ko} 재학습 타임아웃 (10분 초과)")
        logger.error("[retrain] 타임아웃: %s", crop_ko)
    except Exception as e:
        results.append(f"{crop_ko} 재학습 오류: {e}")
        logger.error("[retrain] 오류: %s — %s", crop_ko, e)

    return " | ".join(results) if results else "재학습 결과 없음"


def _maybe_trigger_retrain(
    crop_ko: str,
    bg: BackgroundTasks,
) -> tuple[bool, str]:
    """임계치 도달 시 백그라운드 재학습 예약. (triggered, message_ko) 반환."""
    counts = _get_counts(crop_ko)
    h_count = counts["harvest"]
    g_count = counts["growth"]

    # 재학습 모드 결정
    mode = None
    if h_count > 0 and h_count % _THRESHOLD_HARVEST == 0:
        mode = "both"   # 수확 데이터 임계치: M1+M2 모두 재학습
    elif g_count > 0 and g_count % _THRESHOLD_GROWTH == 0:
        mode = "m1"     # 생육 데이터 임계치: M1만 재학습

    if mode is None:
        return False, ""

    # 공개 데모: 실제 재학습(subprocess, 10분 점유) 차단 → 시뮬레이션 로그만.
    #   무인증/대량 POST로 재학습을 반복 트리거하는 자원고갈(DoS) 경로 제거.
    if _PUBLIC_DEMO:
        msg = (f"[데모] {crop_ko} 재학습 임계치 도달(수확 {h_count}건 / 생육 {g_count}건) "
               f"— 시뮬레이션(실제 학습 미실행)")
        logger.info("[data_collection] %s", msg)
        return False, msg

    msg = (f"신규 {'수확' if mode == 'both' else '생육'} 데이터 임계치 도달 "
           f"(수확 {h_count}건 / 생육 {g_count}건) — {crop_ko} 재학습 예약")
    logger.info("[data_collection] %s", msg)
    bg.add_task(_trigger_retrain, crop_ko, mode)
    return True, msg


# ── 시작 시 초기화 ─────────────────────────────────────────────────────────────
_ensure_dirs()
_load_retrain_state()


# ── 라우터 엔드포인트 ─────────────────────────────────────────────────────────

@router.post("/growth", response_model=GrowthRecordResponse, summary="주간 생육 측정값 수신")
def receive_growth(
    body: GrowthRecord,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth),
) -> GrowthRecordResponse:
    """주간 생육 측정값을 수신하여 DB(없으면 JSON 파일)에 저장합니다.

    - 인증 필수 + farm_id 소유권 검증(무인증 모델오염 차단)
    - 모든 환경·생육 필드는 선택 사항 — 입력된 필드만 저장
    - VPD 미입력 시 온도·습도에서 자동 계산
    - 생육 데이터 30건 누적 시 M1 모델 자동 재학습 예약
    """
    _require_owner(user, body.farm_id)
    rec_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    # VPD 자동 계산
    vpd = body.vpd_kpa
    if vpd is None:
        vpd = _calc_vpd(body.temp_internal, body.humidity_int)

    record: dict[str, Any] = {
        "id":           rec_id,
        "farm_id":      body.farm_id,
        "crop_ko":      body.crop_ko,
        "recorded_date": str(body.recorded_date),
        "recorded_at":  now_iso,
        "source":       body.source,
        # 환경값
        "temp_internal":  body.temp_internal,
        "humidity_int":   body.humidity_int,
        "co2_ppm":        body.co2_ppm,
        "solar_rad":      body.solar_rad,
        "ec_dsm":         body.ec_dsm,
        "soil_temp":      body.soil_temp,
        "vpd_kpa":        vpd,
        # 생육값
        "plant_height_cm":  body.plant_height_cm,
        "leaf_count":       body.leaf_count,
        "fruit_count":      body.fruit_count,
        "stem_diameter_mm": body.stem_diameter_mm,
        "chlorophyll_spad": body.chlorophyll_spad,
        "notes":            body.notes,
    }

    # DB 저장 시도 → 실패 시 JSON 폴백
    db_id = _save_to_db("growth_records", record)
    if db_id is None:
        _save_to_json(_GROWTH_DIR, body.crop_ko, record)
        stored_where = "json_file"
    else:
        stored_where = "db"

    # 카운터 업데이트
    counts = _get_counts(body.crop_ko)
    counts["growth"] += 1
    total = counts["growth"]

    # 임계치 확인 → 재학습 예약
    triggered, retrain_msg = _maybe_trigger_retrain(body.crop_ko, background_tasks)

    logger.info(
        "[data_collection] growth 수신: farm=%s crop=%s stored=%s total=%d",
        body.farm_id, body.crop_ko, stored_where, total,
    )

    return GrowthRecordResponse(
        status=f"stored_{stored_where}",
        message_ko=f"{body.crop_ko} 생육 측정값 저장 완료 (누적 {total}건)",
        record_id=rec_id,
        total_count=total,
        retrain_triggered=triggered,
    )


@router.post("/harvest", response_model=HarvestRecordResponse, summary="수확량 실측값 수신")
def receive_harvest(
    body: HarvestRecord,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_auth),
) -> HarvestRecordResponse:
    """수확량 실측값을 수신하여 저장합니다.

    - 인증 필수 + farm_id 소유권 검증(무인증 모델오염·재학습DoS 차단)
    - yield_kg_m2 (kg/m²) 는 필수 입력
    - total_yield_kg 미입력 시 yield_kg_m2 × area_m2 자동 계산
    - 수확 데이터 10건 누적 시 M1+M2 모델 자동 재학습 예약
    """
    _require_owner(user, body.farm_id)
    rec_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    # total_yield_kg 자동 계산
    total_kg = body.total_yield_kg
    if total_kg is None and body.area_m2 is not None:
        total_kg = round(body.yield_kg_m2 * body.area_m2, 2)

    # 재배 일수 자동 계산
    growing_days = body.growing_days
    if growing_days is None and body.planting_date is not None:
        growing_days = (body.harvest_date - body.planting_date).days

    # 시즌 평균 환경값 자동 채우기 — sensor_data DB에서 정식일~수확일 평균 계산
    season_avg_temp     = body.season_avg_temp
    season_avg_humidity = body.season_avg_humidity
    if (season_avg_temp is None or season_avg_humidity is None) \
            and body.planting_date is not None:
        auto_temp, auto_humi = _auto_season_env(
            body.farm_id,
            str(body.planting_date),
            str(body.harvest_date),
        )
        if season_avg_temp is None and auto_temp is not None:
            season_avg_temp = auto_temp
            logger.info(
                "[data_collection] season_avg_temp 자동 계산: farm=%s crop=%s temp=%.1f",
                body.farm_id, body.crop_ko, auto_temp,
            )
        if season_avg_humidity is None and auto_humi is not None:
            season_avg_humidity = auto_humi

    record: dict[str, Any] = {
        "id":               rec_id,
        "farm_id":          body.farm_id,
        "crop_ko":          body.crop_ko,
        "harvest_date":     str(body.harvest_date),
        "recorded_at":      now_iso,
        "source":           body.source,
        "yield_kg_m2":      body.yield_kg_m2,
        "area_m2":          body.area_m2,
        "total_yield_kg":   total_kg,
        "planting_date":    str(body.planting_date) if body.planting_date else None,
        "growing_days":     growing_days,
        "season_avg_temp":  season_avg_temp,
        "season_avg_humidity": season_avg_humidity,
        "notes":            body.notes,
    }

    db_id = _save_to_db("harvest_records", record)
    if db_id is None:
        _save_to_json(_HARVEST_DIR, body.crop_ko, record)
        stored_where = "json_file"
    else:
        stored_where = "db"

    counts = _get_counts(body.crop_ko)
    counts["harvest"] += 1
    total = counts["harvest"]

    triggered, retrain_msg = _maybe_trigger_retrain(body.crop_ko, background_tasks)

    logger.info(
        "[data_collection] harvest 수신: farm=%s crop=%s yield=%.2f stored=%s total=%d",
        body.farm_id, body.crop_ko, body.yield_kg_m2, stored_where, total,
    )

    # 자동 채우기된 환경값 알림 메시지 생성
    env_auto_msg = ""
    if season_avg_temp is not None and body.season_avg_temp is None:
        env_auto_msg = f" (시즌 평균 온도 {season_avg_temp}°C 자동 계산됨)"
    elif season_avg_temp is None:
        env_auto_msg = " (환경값 없음 — 온도·습도 입력 시 드리프트 정확도 향상)"

    return HarvestRecordResponse(
        status=f"stored_{stored_where}",
        message_ko=f"{body.crop_ko} 수확량 실측값 저장 완료 (누적 {total}건){env_auto_msg}",
        record_id=rec_id,
        total_count=total,
        retrain_triggered=triggered,
        retrain_message_ko=retrain_msg,
    )


@router.get("/growth", summary="생육 측정 기록 이력 조회")
def get_growth_history(
    farm_id: str = Query(..., description="농장 ID"),
    limit: int  = Query(50, ge=1, le=200, description="반환할 최대 레코드 수"),
    user: dict = Depends(require_auth),
) -> dict:
    """특정 농장의 생육 측정 기록 이력을 JSON 파일에서 읽어 반환합니다. (인증+소유권)"""
    _require_owner(user, farm_id)
    records: list[dict] = []
    if _GROWTH_DIR.exists():
        for fpath in _GROWTH_DIR.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if data.get("farm_id") == farm_id:
                    records.append(data)
            except Exception:
                pass
    # recorded_date 기준 내림차순
    records.sort(
        key=lambda r: r.get("recorded_date") or (r.get("recorded_at") or "")[:10],
        reverse=True,
    )
    return {"farm_id": farm_id, "records": records[:limit], "total": len(records)}


@router.patch("/growth/{record_id}/label", summary="생육 기록 전문가 레이블 설정")
def label_growth_record(
    record_id: str,
    body: ExpertLabelRequest,
    user: dict = Depends(require_auth),
) -> dict:
    """전문가가 개별 생육 측정 기록에 레이블을 설정합니다.

    - 'bad': M1 재학습 시 해당 행 제외
    - 'outlier': 주의 마킹 (기본 제외 안 함, 향후 엔진 확장 가능)
    - 'ok': 정상 (기본값)
    - admin/manager 전용 (일반 농가 계정 불허)
    """
    role = (user or {}).get("role", "")
    if role not in ("admin", "manager", "superadmin"):
        raise HTTPException(status_code=403, detail="전문가 레이블은 admin/manager만 설정할 수 있습니다.")

    # record_id 일치 JSON 파일 탐색
    target_path: Optional[Path] = None
    target_data: dict = {}
    if _GROWTH_DIR.exists():
        for fpath in _GROWTH_DIR.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if data.get("id") == record_id:
                    target_path = fpath
                    target_data = data
                    break
            except Exception:
                continue

    if target_path is None:
        raise HTTPException(status_code=404, detail=f"생육 기록을 찾을 수 없습니다: {record_id}")

    prev_label = target_data.get("expert_label")
    target_data["expert_label"] = body.expert_label
    if body.reason:
        target_data["expert_label_reason"] = body.reason
    target_data["expert_labeled_at"] = datetime.now(timezone.utc).isoformat()
    target_data["expert_labeled_by"] = user.get("username", "unknown")

    target_path.write_text(json.dumps(target_data, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "[data_collection] expert_label 설정: record=%s label=%s -> %s by=%s",
        record_id, prev_label, body.expert_label, user.get("username"),
    )
    return {
        "record_id": record_id,
        "farm_id": target_data.get("farm_id"),
        "crop_ko": target_data.get("crop_ko"),
        "recorded_date": target_data.get("recorded_date"),
        "expert_label": body.expert_label,
        "prev_label": prev_label,
        "message_ko": f"레이블 설정 완료: {body.expert_label}" + (f" (사유: {body.reason})" if body.reason else ""),
    }


@router.get("/growth/labels", summary="전문가 레이블 현황 조회")
def get_label_summary(
    crop_ko: Optional[str] = Query(None, description="작목 필터 (없으면 전체)"),
    user: dict = Depends(require_auth),
) -> dict:
    """전문가 레이블이 설정된 생육 기록 현황을 반환합니다. admin/manager 전용."""
    role = (user or {}).get("role", "")
    if role not in ("admin", "manager", "superadmin"):
        raise HTTPException(status_code=403, detail="admin/manager만 조회할 수 있습니다.")

    summary: dict[str, dict] = {}  # crop -> {ok, bad, outlier, unlabeled}
    labeled_records: list[dict] = []

    if _GROWTH_DIR.exists():
        for fpath in _GROWTH_DIR.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            crop = data.get("crop_ko", "unknown")
            if crop_ko and crop != crop_ko:
                continue
            lbl = data.get("expert_label") or "unlabeled"
            if crop not in summary:
                summary[crop] = {"ok": 0, "bad": 0, "outlier": 0, "unlabeled": 0}
            summary[crop][lbl] = summary[crop].get(lbl, 0) + 1
            if lbl != "unlabeled":
                labeled_records.append({
                    "id": data.get("id"),
                    "farm_id": data.get("farm_id"),
                    "crop_ko": crop,
                    "recorded_date": data.get("recorded_date"),
                    "expert_label": lbl,
                    "expert_label_reason": data.get("expert_label_reason"),
                    "expert_labeled_by": data.get("expert_labeled_by"),
                    "expert_labeled_at": data.get("expert_labeled_at"),
                })

    labeled_records.sort(key=lambda r: r.get("expert_labeled_at") or "", reverse=True)
    return {"summary": summary, "labeled": labeled_records, "total_labeled": len(labeled_records)}


@router.get("/harvest", summary="수확량 기록 이력 조회")
def get_harvest_history(
    farm_id: str = Query(..., description="농장 ID"),
    limit: int  = Query(50, ge=1, le=200, description="반환할 최대 레코드 수"),
    user: dict = Depends(require_auth),
) -> dict:
    """특정 농장의 수확량 기록 이력을 JSON 파일에서 읽어 반환합니다. (인증+소유권)"""
    _require_owner(user, farm_id)
    records: list[dict] = []
    if _HARVEST_DIR.exists():
        for fpath in _HARVEST_DIR.glob("*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if data.get("farm_id") == farm_id:
                    records.append(data)
            except Exception:
                pass
    # harvest_date 기준 내림차순
    records.sort(
        key=lambda r: r.get("harvest_date") or (r.get("recorded_at") or "")[:10],
        reverse=True,
    )
    return {"farm_id": farm_id, "records": records[:limit], "total": len(records)}


@router.get("/status", response_model=DataStatusResponse, summary="전체 수집 현황")
def get_data_status() -> DataStatusResponse:
    """전체 작목별 데이터 수집 현황을 반환합니다."""
    from models.crop_config import CROP_CONFIGS

    items = []
    total_g = total_h = 0
    for crop_ko in CROP_CONFIGS:
        g_count = _count_files(_GROWTH_DIR,  crop_ko)
        h_count = _count_files(_HARVEST_DIR, crop_ko)
        _counts.setdefault(crop_ko, {"growth": g_count, "harvest": h_count})

        # 최신 파일 타임스탬프
        def _latest_ts(d: Path, c: str) -> Optional[str]:
            safe = c.replace("/", "_").replace("\\", "_")
            files = sorted(d.glob(f"{safe}_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            if not files:
                return None
            try:
                data = json.loads(files[0].read_text(encoding="utf-8"))
                return data.get("recorded_at")
            except Exception:
                return None

        last_g = _latest_ts(_GROWTH_DIR,  crop_ko)
        last_h = _latest_ts(_HARVEST_DIR, crop_ko)

        retrain_ts = _last_retrain.get(crop_ko)
        r_status = f"완료 ({retrain_ts[:10]})" if retrain_ts else "대기"

        items.append(DataCountItem(
            crop_ko=crop_ko,
            growth_count=g_count,
            harvest_count=h_count,
            last_growth_at=last_g,
            last_harvest_at=last_h,
            retrain_status=r_status,
        ))
        total_g += g_count
        total_h += h_count

    return DataStatusResponse(
        items=items,
        total_growth=total_g,
        total_harvest=total_h,
        retrain_threshold_growth=_THRESHOLD_GROWTH,
        retrain_threshold_harvest=_THRESHOLD_HARVEST,
    )


@router.get("/status/{farm_id}", response_model=DataStatusResponse, summary="농장별 수집 현황")
def get_farm_data_status(farm_id: str) -> DataStatusResponse:
    """특정 농장의 데이터 수집 현황을 반환합니다."""
    from models.crop_config import CROP_CONFIGS

    items = []
    total_g = total_h = 0
    for crop_ko in CROP_CONFIGS:
        safe = crop_ko.replace("/", "_").replace("\\", "_")

        def _farm_count(d: Path) -> int:
            if not d.exists():
                return 0
            cnt = 0
            for f in d.glob(f"{safe}_*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if data.get("farm_id") == farm_id:
                        cnt += 1
                except Exception:
                    pass
            return cnt

        g_count = _farm_count(_GROWTH_DIR)
        h_count = _farm_count(_HARVEST_DIR)
        if g_count == 0 and h_count == 0:
            continue

        items.append(DataCountItem(
            crop_ko=crop_ko,
            growth_count=g_count,
            harvest_count=h_count,
        ))
        total_g += g_count
        total_h += h_count

    return DataStatusResponse(
        farm_id=farm_id,
        items=items,
        total_growth=total_g,
        total_harvest=total_h,
        retrain_threshold_growth=_THRESHOLD_GROWTH,
        retrain_threshold_harvest=_THRESHOLD_HARVEST,
    )
