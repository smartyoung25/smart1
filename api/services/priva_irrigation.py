"""Priva 관수 최적화 엔진.

프리바(Priva-Netafim) 관수 시스템 매뉴얼 (770pp, Korean) 에서 추출한
알고리즘을 구현한다.

추출된 알고리즘 5가지
─────────────────────
1. 적산일사 시작 (Radiation sum start, I 400 §8)
   - 일출 후 누적 일사량이 trigger_j_cm2 (J/cm²) 를 넘을 때마다 1회 관수
   - Range radiation start/end (200–800 W/m²) 로 최소 휴지시간을 일사에 비례해 단축

2. 증산량 기반 공급량 (Transpiration-based supply, I 400 §9 / I 419 §15)
   공식: supply_mm = ET₀ × Kc × 증산상수 × 작물크기계수(%)÷100
   - 증산상수(transpiration_constant): 작목별 0.8~1.2
   - 작물크기계수(plant_size_pct):     0~1000 %, 완전 엽면피복=100 %

3. P/I 배액 교정 (P/I drain correction, I 400 §20)
   - P-action(배액교정 P-작용): P_factor × drain_error  [l/m²/cycle]
   - I-action(배액교정 I-작용): 누적항, ±max_I_action 범위로 클램프
   - 전형값: P=0.60, I=0.10, max_I=공급량의 25 %

4. 3-상황 관수 스케줄 (Phase-based schedule, I 400 / I 401)
   - Phase 1 (아침, 일출+30분~): 소량, EC 낮은 처방으로 배지 적심
   - Phase 2 (낮, 10:00~16:00): 주요 관수, 목표 배액률 유지
   - Phase 3 (오후, 16:00~일몰-2h): 감량, 야간 배지 함수율 조정

5. 일사 배액% 증가 (Radiation increase drain%, I 400 §24)
   - 강한 일사에서 목표 배액률을 소폭 높여 염류 세척
   공식: drain_target = base_pct + radiation_increase_pct × (gsr / 500 W/m²)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 기본 상수 ─────────────────────────────────────────────────────────────────

# Priva 매뉴얼 §I 400.2 Range radiation 예시값
_RANGE_RAD_START_DEFAULT = 200.0   # W/m² — 이 이상부터 휴지시간 단축 시작
_RANGE_RAD_END_DEFAULT   = 800.0   # W/m² — 이 이상에서 최소 휴지시간으로 고정

# 증산상수 (작목별 경험 계수; FAO-56 + Priva §I 400 §15 기준)
_TRANSPIRATION_CONSTANT: dict[str, float] = {
    "딸기":     0.80,
    "방울토마토": 1.10,
    "완숙토마토": 1.15,
    "참외":     0.90,
    "파프리카":  1.05,
}
_TRANSPIRATION_CONSTANT_DEFAULT = 1.00

# J/cm² → l/m²  변환 (1 J/cm² = 0.01 MJ/m²; 1 MJ/m² ≈ 0.24 mm ET₀)
_J_CM2_TO_MJ_M2 = 0.01


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────

@dataclass
class PrivaIrrigationConfig:
    """농가·작기별 Priva 관수 설정.

    매뉴얼 I 400 Auto Start/Strategy 파라미터 모음.
    """
    crop_ko:          str   = "딸기"
    growth_stage:     str   = "mid"          # "initial"|"dev"|"mid"|"late"
    plant_size_pct:   float = 100.0          # 작물크기계수 0~1000 %
    drain_target_pct: float = 20.0           # 목표 배액률 %
    # --- 적산일사 트리거 ---
    trigger_j_cm2:    float = 80.0           # 1회 관수 트리거 일사량 (J/cm²)
    range_rad_start:  float = _RANGE_RAD_START_DEFAULT   # W/m²
    range_rad_end:    float = _RANGE_RAD_END_DEFAULT     # W/m²
    rad_min_rest_reduction_pct: float = 60.0  # 최소 휴지시간 최대 단축 %
    # --- P/I 배액 교정 ---
    p_factor:         float = 0.60           # P 인수 (비례)
    i_factor:         float = 0.10           # I 인수 (적분)
    max_i_action_pct: float = 25.0           # 최대 I 작용량 (공급량의 %)
    # --- 공급 기본값 ---
    supply_per_shot_ml: float = 200.0        # 1회 관수량 (ml/slab)
    slab_area_m2:       float = 0.15         # 슬라브 면적 (m²)
    # --- 일사 배액% 증가 ---
    radiation_increase_drain_pct: float = 5.0  # 최대 배액% 증가폭


@dataclass
class PIControllerState:
    """P/I 배액 교정용 적분 상태 (한 밸브그룹 당 1개 인스턴스)."""
    i_action_lm2: float = 0.0    # 누적 I 작용 [l/m²]

    def update(
        self,
        drain_actual_pct: float,
        drain_target_pct: float,
        p_factor: float = 0.60,
        i_factor: float = 0.10,
        max_i_lm2: float = 0.05,
    ) -> float:
        """1 주기 후 P/I 교정값 반환 (양수=공급 증가, 음수=공급 감소).

        Args:
            drain_actual_pct: 실측 배액률 (%)
            drain_target_pct: 목표 배액률 (%)
            p_factor:         P 인수 (Priva 기본 0.60)
            i_factor:         I 인수 (Priva 기본 0.10)
            max_i_lm2:        최대 I 작용량 [l/m²] (공급량의 25 % 권장)

        Returns:
            total_correction_lm2: P+I 교정량 [l/m²/cycle]
        """
        error = drain_target_pct - drain_actual_pct   # 배액 부족이면 양수
        p_corr = p_factor * error * 0.01              # % → l/m² (0.01 스케일링)
        self.i_action_lm2 += i_factor * error * 0.01
        self.i_action_lm2 = max(-max_i_lm2, min(max_i_lm2, self.i_action_lm2))
        return round(p_corr + self.i_action_lm2, 4)

    def reset(self) -> None:
        """배액률이 정상 범위로 복귀했을 때 I항 리셋."""
        self.i_action_lm2 = 0.0


@dataclass
class IrrigationPhase:
    """Priva 1개 상황(Phase) 스케줄."""
    phase_no:          int
    name_ko:           str
    start_hhmm:        str              # "06:30"
    end_hhmm:          str              # "10:00"
    supply_ml:         float            # 1회 공급량
    n_max:             int              # 최대 관수 횟수
    drain_target_pct:  float            # 이 상황의 목표 배액률
    note:              str = ""


@dataclass
class PrivaScheduleResult:
    """compute_priva_schedule() 반환값."""
    crop_ko:            str
    growth_stage:       str
    date_str:           str
    et0_mm:             float
    etc_mm:             float
    kc:                 float
    plant_size_pct:     float
    transpiration_mm:   float           # 증산량 추정 (mm)
    supply_total_ml:    float           # 하루 총 공급량 (ml/slab)
    n_irrigations:      int             # 권장 관수 횟수
    phases:             list[IrrigationPhase]
    drain_target_pct:   float           # 당일 최종 목표 배액률
    radiation_j_cm2:    float           # 당일 누적 일사 (J/cm²)
    trigger_j_cm2:      float           # 사용된 트리거 임계값
    pi_correction_lm2:  float           # P/I 교정량 (l/m²)
    method:             str = "priva_radiation_sum_transpiration"
    note:               str = ""

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "phases"}
        d["phases"] = [ph.__dict__ for ph in self.phases]
        return d


# ── 보조 함수 ─────────────────────────────────────────────────────────────────

def _parse_kc(crop_ko: str, growth_stage: str) -> float:
    """작목·생육단계별 Kc 반환. models.crop_config 에서 조회."""
    try:
        from models.crop_config import CROP_CONFIGS  # type: ignore
        cfg = CROP_CONFIGS.get(crop_ko)
        if cfg:
            return float(cfg.kc_stages.get(growth_stage, cfg.kc_stages.get("mid", 1.0)))
    except Exception:
        pass
    return 1.0


def calc_radiation_sum_n_irrigations(
    daily_gsr_mj_m2: float,
    trigger_j_cm2: float = 80.0,
    min_n: int = 2,
    max_n: int = 16,
) -> int:
    """일사 합계 기준 하루 관수 횟수 계산.

    Priva §I 400 §8 Radiation sum start 알고리즘.
    - 일출~일몰 동안 누적일사 trigger_j_cm2 마다 1회 관수
    - J/cm² 단위 변환: 1 MJ/m² = 100 J/cm²

    Args:
        daily_gsr_mj_m2: 하루 총 일사량 (MJ/m²)
        trigger_j_cm2:   1회 트리거 임계값 (J/cm²)
        min_n, max_n:    관수 횟수 범위

    Returns:
        n_irrigations: 권장 관수 횟수
    """
    if daily_gsr_mj_m2 <= 0 or trigger_j_cm2 <= 0:
        return min_n
    # MJ/m² → J/cm² 변환 (1 MJ/m² = 100 J/cm²)
    gsr_j_cm2 = daily_gsr_mj_m2 * 100.0
    n_raw = gsr_j_cm2 / trigger_j_cm2
    return max(min_n, min(max_n, round(n_raw)))


def calc_transpiration_supply_mm(
    et0_mm: float,
    kc: float,
    transpiration_constant: float = 1.0,
    plant_size_pct: float = 100.0,
    drain_target_pct: float = 20.0,
) -> float:
    """증산량 기반 1일 목표 공급량 (mm) 계산.

    Priva §I 400 §15 Plant size factor 모델:
        증발량(mm) = ET₀ × Kc × 증산상수 × 작물크기계수(%)÷100
        공급량(mm) = 증발량 / (1 - 배액률/100)   ← 배액 손실 보정

    Args:
        et0_mm:                  Hargreaves ET₀ (mm/day)
        kc:                      FAO-56 작물계수 (Kc)
        transpiration_constant:  작목별 증산상수 (0.8~1.2)
        plant_size_pct:          작물크기계수 (0~1000 %)
        drain_target_pct:        목표 배액률 (%)

    Returns:
        supply_mm: 총 공급 목표량 (mm/day)
    """
    etc_mm = et0_mm * kc
    transpiration_mm = etc_mm * transpiration_constant * (plant_size_pct / 100.0)
    drain_factor = max(0.5, 1.0 - drain_target_pct / 100.0)
    supply_mm = transpiration_mm / drain_factor
    return round(max(supply_mm, 0.0), 2)


def calc_radiation_adjusted_drain_pct(
    base_drain_pct: float,
    solar_avg_wm2: float,
    radiation_increase_pct: float = 5.0,
    ref_rad_wm2: float = 500.0,
) -> float:
    """일사 강도에 따른 목표 배액률 동적 조정.

    Priva §I 400 §24 Radiation increase drain%:
        drain_target = base + increase_pct × min(solar / ref_rad, 1.0)

    강한 일사 → 더 많은 공급 → 배액률 소폭 증가 → 염류 세척 효과

    Args:
        base_drain_pct:         기본 목표 배액률 (%)
        solar_avg_wm2:          평균 일사량 (W/m²)
        radiation_increase_pct: 최대 배액% 증가폭 (Priva 기본 0~100 %)
        ref_rad_wm2:            기준 일사량 (W/m²)

    Returns:
        adjusted_drain_pct: 조정된 목표 배액률 (%)
    """
    ratio = min(solar_avg_wm2 / max(ref_rad_wm2, 1.0), 1.0)
    adjusted = base_drain_pct + radiation_increase_pct * ratio
    return round(min(adjusted, base_drain_pct + radiation_increase_pct), 1)


def calc_rest_time_reduction_pct(
    solar_wm2: float,
    range_rad_start: float = _RANGE_RAD_START_DEFAULT,
    range_rad_end: float = _RANGE_RAD_END_DEFAULT,
    max_reduction_pct: float = 60.0,
) -> float:
    """현재 일사량 기준 최소 휴지시간 단축 비율 계산.

    Priva §I 400.2 §2 Radiation adjustment minimum rest time:
        - range_rad_start 이하: 단축 없음 (0 %)
        - range_rad_end 이상: 최대 단축 (max_reduction_pct %)
        - 중간: 선형 보간

    Args:
        solar_wm2:         현재 일사량 (W/m²)
        range_rad_start:   단축 시작 일사량 (W/m²)
        range_rad_end:     최대 단축 일사량 (W/m²)
        max_reduction_pct: 최대 단축 % (Priva 기본 60 %)

    Returns:
        reduction_pct: 휴지시간 단축 비율 (0~max_reduction_pct %)
    """
    if solar_wm2 <= range_rad_start:
        return 0.0
    if solar_wm2 >= range_rad_end:
        return max_reduction_pct
    ratio = (solar_wm2 - range_rad_start) / max(range_rad_end - range_rad_start, 1.0)
    return round(ratio * max_reduction_pct, 1)


def build_phase_schedule(
    n_total: int,
    supply_total_ml: float,
    drain_target_pct: float,
    solar_avg_wm2: float = 300.0,
) -> list[IrrigationPhase]:
    """3-상황(Phase) 관수 스케줄 생성.

    Priva §I 401 Phase 시스템:
        Phase 1 (아침): 일출 후 첫 관수 — 배지 적심, 적은 양
        Phase 2 (낮):   주요 생산 관수 — 목표 배액률 유지
        Phase 3 (오후): 일몰 전 마무리 — 야간 함수율 조정

    배분 비율 (Priva 전형 사례):
        Phase 1: 전체의 15 % (초기 적심)
        Phase 2: 전체의 65 % (주요 관수)
        Phase 3: 전체의 20 % (마무리)

    Args:
        n_total:          총 관수 횟수
        supply_total_ml:  하루 총 공급량 (ml/slab)
        drain_target_pct: 기본 목표 배액률 (%)
        solar_avg_wm2:    평균 일사량 (W/m²)

    Returns:
        [Phase1, Phase2, Phase3]
    """
    # 일사에 따라 Phase2 비율 조정 (강한 일사 → Phase2 비중 ↑)
    phase2_ratio = 0.65 + min(0.10, (solar_avg_wm2 - 300) / 2000.0)
    phase1_ratio = 0.15
    phase3_ratio = 1.0 - phase1_ratio - phase2_ratio

    n1 = max(1, round(n_total * phase1_ratio))
    n3 = max(1, round(n_total * phase3_ratio))
    n2 = max(1, n_total - n1 - n3)

    ml1 = round(supply_total_ml * phase1_ratio / max(n1, 1))
    ml3 = round(supply_total_ml * phase3_ratio / max(n3, 1))
    ml2 = round(supply_total_ml * phase2_ratio / max(n2, 1))

    return [
        IrrigationPhase(
            phase_no=1,
            name_ko="아침 (적심)",
            start_hhmm="06:30",
            end_hhmm="10:00",
            supply_ml=ml1,
            n_max=n1,
            drain_target_pct=max(drain_target_pct - 5.0, 10.0),
            note="배지 초기 적심, 목표 배액률 보다 낮게 유지",
        ),
        IrrigationPhase(
            phase_no=2,
            name_ko="낮 (주요 관수)",
            start_hhmm="10:00",
            end_hhmm="16:00",
            supply_ml=ml2,
            n_max=n2,
            drain_target_pct=drain_target_pct,
            note="주요 생산 관수, 목표 배액률 준수",
        ),
        IrrigationPhase(
            phase_no=3,
            name_ko="오후 (마무리)",
            start_hhmm="16:00",
            end_hhmm="18:30",
            supply_ml=ml3,
            n_max=n3,
            drain_target_pct=min(drain_target_pct + 3.0, 35.0),
            note="야간 배지 함수율 조정, 일몰 2시간 전 종료",
        ),
    ]


# ── 메인 스케줄 계산 함수 ─────────────────────────────────────────────────────

def compute_priva_schedule(
    et0_mm: float,
    daily_gsr_mj_m2: float,
    solar_avg_wm2: float,
    config: PrivaIrrigationConfig,
    pi_state: Optional[PIControllerState] = None,
    drain_actual_pct: Optional[float] = None,
    date_str: str = "",
) -> PrivaScheduleResult:
    """Priva 관수 최적화 알고리즘 통합 실행.

    Args:
        et0_mm:            Hargreaves ET₀ (mm/day)
        daily_gsr_mj_m2:   하루 누적 일사량 (MJ/m²)
        solar_avg_wm2:     평균 일사량 (W/m²)
        config:            PrivaIrrigationConfig 설정
        pi_state:          P/I 컨트롤러 상태 (연속 운용 시 재사용)
        drain_actual_pct:  전날 실측 배액률 (P/I 교정에 사용)
        date_str:          날짜 문자열 (YYYY-MM-DD, 메타 정보용)

    Returns:
        PrivaScheduleResult
    """
    import datetime as _dt
    if not date_str:
        date_str = _dt.date.today().isoformat()

    # ── 1. Kc + 증산상수 ─────────────────────────────────────────────────────
    kc = _parse_kc(config.crop_ko, config.growth_stage)
    t_const = _TRANSPIRATION_CONSTANT.get(config.crop_ko, _TRANSPIRATION_CONSTANT_DEFAULT)

    # ── 2. 일사 배액% 증가 조정 ──────────────────────────────────────────────
    drain_adj_pct = calc_radiation_adjusted_drain_pct(
        base_drain_pct=config.drain_target_pct,
        solar_avg_wm2=solar_avg_wm2,
        radiation_increase_pct=config.radiation_increase_drain_pct,
    )

    # ── 3. 증산량 기반 공급량 계산 ───────────────────────────────────────────
    supply_mm = calc_transpiration_supply_mm(
        et0_mm=et0_mm,
        kc=kc,
        transpiration_constant=t_const,
        plant_size_pct=config.plant_size_pct,
        drain_target_pct=drain_adj_pct,
    )
    etc_mm = round(et0_mm * kc, 2)
    transpiration_mm = round(etc_mm * t_const * (config.plant_size_pct / 100.0), 2)

    # ml/slab/day 변환 (1 mm/m² = 1 l/m²; slab = slab_area_m2)
    supply_total_ml = round(supply_mm * config.slab_area_m2 * 1000.0, 0)
    supply_total_ml = max(supply_total_ml, config.supply_per_shot_ml * 2)

    # ── 4. 적산일사 기반 관수 횟수 ───────────────────────────────────────────
    gsr_j_cm2 = daily_gsr_mj_m2 * 100.0   # MJ/m² → J/cm²
    n_rad = calc_radiation_sum_n_irrigations(
        daily_gsr_mj_m2=daily_gsr_mj_m2,
        trigger_j_cm2=config.trigger_j_cm2,
    )

    # 공급량 기반 횟수 보정 (너무 적은 1회 공급량 방지)
    n_supply = max(2, round(supply_total_ml / max(config.supply_per_shot_ml, 50.0)))

    # 두 방법 블렌딩: 일사 70 % + 공급량 30 %
    n_blend = max(2, min(16, round(0.70 * n_rad + 0.30 * n_supply)))

    # ── 5. P/I 배액 교정 ─────────────────────────────────────────────────────
    pi_correction_lm2 = 0.0
    if pi_state is not None and drain_actual_pct is not None:
        max_i = config.supply_per_shot_ml * config.slab_area_m2 * (config.max_i_action_pct / 100.0)
        pi_correction_lm2 = pi_state.update(
            drain_actual_pct=drain_actual_pct,
            drain_target_pct=drain_adj_pct,
            p_factor=config.p_factor,
            i_factor=config.i_factor,
            max_i_lm2=max_i,
        )
        # P/I 교정량을 공급 횟수에 반영
        corr_ml = pi_correction_lm2 * config.slab_area_m2 * 1000.0
        supply_total_ml = round(max(supply_total_ml + corr_ml, config.supply_per_shot_ml * 2), 0)

    # ── 6. 3-상황 스케줄 생성 ────────────────────────────────────────────────
    phases = build_phase_schedule(
        n_total=n_blend,
        supply_total_ml=supply_total_ml,
        drain_target_pct=drain_adj_pct,
        solar_avg_wm2=solar_avg_wm2,
    )

    # ── 7. 결과 메모 ─────────────────────────────────────────────────────────
    rest_reduction = calc_rest_time_reduction_pct(
        solar_wm2=solar_avg_wm2,
        range_rad_start=config.range_rad_start,
        range_rad_end=config.range_rad_end,
        max_reduction_pct=config.rad_min_rest_reduction_pct,
    )
    note = (
        f"ET₀={et0_mm}mm, Kc={kc:.2f}({config.growth_stage}), ETc={etc_mm}mm, "
        f"증산상수={t_const}, 작물크기={config.plant_size_pct}% → "
        f"증산량={transpiration_mm}mm, 공급={supply_mm}mm "
        f"({supply_total_ml:.0f}ml/slab, {n_blend}회); "
        f"일사트리거={config.trigger_j_cm2}J/cm²({gsr_j_cm2:.0f}J/cm²누적), "
        f"배액목표={drain_adj_pct}%(기본{config.drain_target_pct}%+일사{drain_adj_pct-config.drain_target_pct:.1f}%), "
        f"휴지단축={rest_reduction}%, P/I교정={pi_correction_lm2:+.3f}l/m²"
    )

    return PrivaScheduleResult(
        crop_ko=config.crop_ko,
        growth_stage=config.growth_stage,
        date_str=date_str,
        et0_mm=et0_mm,
        etc_mm=etc_mm,
        kc=kc,
        plant_size_pct=config.plant_size_pct,
        transpiration_mm=transpiration_mm,
        supply_total_ml=supply_total_ml,
        n_irrigations=n_blend,
        phases=phases,
        drain_target_pct=drain_adj_pct,
        radiation_j_cm2=round(gsr_j_cm2, 1),
        trigger_j_cm2=config.trigger_j_cm2,
        pi_correction_lm2=round(pi_correction_lm2, 4),
        method="priva_radiation_sum_transpiration",
        note=note,
    )


# ── 편의 함수 ─────────────────────────────────────────────────────────────────

def get_default_config(crop_ko: str, growth_stage: str = "mid") -> PrivaIrrigationConfig:
    """작목별 기본 PrivaIrrigationConfig 생성.

    models.crop_config 의 drain_target_pct / irrigation_target_mm_day 를 반영한다.
    """
    try:
        from models.crop_config import CROP_CONFIGS  # type: ignore
        cfg = CROP_CONFIGS.get(crop_ko)
        if cfg:
            return PrivaIrrigationConfig(
                crop_ko=crop_ko,
                growth_stage=growth_stage,
                drain_target_pct=cfg.drain_target_pct,
                supply_per_shot_ml=cfg.irrigation_target_mm_day * 150.0,  # mm → ml/slab (0.15m²)
            )
    except Exception:
        pass
    return PrivaIrrigationConfig(crop_ko=crop_ko, growth_stage=growth_stage)
