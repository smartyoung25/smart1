import { useState } from "react";
import { colors, radius, shadow } from "../design-system/tokens";

interface Recommendation {
  rank: number;
  action_ko: string;
  profit_delta: number;
  confidence: number;
  tier_action: "checklist" | "approval_required" | "auto";
}

// ── 환경 입력 필드 정의 ────────────────────────────────────────────────────────
interface FieldDef { key: string; label: string; unit: string; min: number; max: number; step: number; placeholder: string; }
const ENV_FIELDS: FieldDef[] = [
  { key: "temp_internal", label: "내부 온도",  unit: "°C",   min: 0,   max: 50,   step: 0.1, placeholder: "예: 22.5" },
  { key: "humidity_int",  label: "내부 습도",  unit: "%",    min: 20,  max: 100,  step: 1,   placeholder: "예: 75" },
  { key: "co2_ppm",       label: "CO₂ 농도",  unit: "ppm",  min: 300, max: 2000, step: 10,  placeholder: "예: 900" },
  { key: "solar_rad",     label: "일사량",     unit: "W/m²", min: 0,   max: 1200, step: 10,  placeholder: "예: 350" },
  { key: "ec_dsm",        label: "EC (양액)",  unit: "dS/m", min: 0.5, max: 5.0,  step: 0.1, placeholder: "예: 2.1" },
  { key: "soil_temp",     label: "지온",       unit: "°C",   min: 5,   max: 35,   step: 0.1, placeholder: "예: 18.0" },
];

// ── 수동 적용 모달 (체크리스트 티어 전용) ──────────────────────────────────────
function ManualApplyModal({ farmId, action, onConfirm, onCancel }: {
  farmId: string;
  action: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [values, setValues]   = useState<Record<string, string>>({});
  const [errors, setErrors]   = useState<Record<string, string>>({});
  const [saving, setSaving]   = useState(false);
  const [apiErr, setApiErr]   = useState<string | null>(null);

  function handleChange(key: string, raw: string) {
    setValues(p => ({ ...p, [key]: raw }));
    setErrors(p => ({ ...p, [key]: "" }));
    setApiErr(null);
  }

  function validate(): boolean {
    const next: Record<string, string> = {};
    let ok = true;
    for (const f of ENV_FIELDS) {
      const raw = (values[f.key] ?? "").trim();
      if (!raw) continue;
      const num = parseFloat(raw);
      if (isNaN(num)) { next[f.key] = "숫자를 입력해 주세요"; ok = false; }
      else if (num < f.min || num > f.max) { next[f.key] = `${f.min}~${f.max} ${f.unit}`; ok = false; }
    }
    setErrors(next);
    return ok;
  }

  async function handleSave() {
    if (!validate()) return;
    const payload: Record<string, number> = {};
    for (const f of ENV_FIELDS) {
      const raw = (values[f.key] ?? "").trim();
      if (raw !== "") payload[f.key] = parseFloat(raw);
    }
    if (Object.keys(payload).length === 0) {
      setApiErr("최소 하나 이상의 환경값을 입력해 주세요.");
      return;
    }
    setSaving(true);
    setApiErr(null);
    try {
      const res = await fetch(`/api/farms/${farmId}/environment/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      onConfirm();
    } catch (e: unknown) {
      setApiErr(e instanceof Error ? e.message : "저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  const filledCount = ENV_FIELDS.filter(f => (values[f.key] ?? "").trim() !== "").length;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 100, padding: "16px",
    }}>
      <div style={{
        background: colors.cloudWhite, borderRadius: radius.card,
        padding: "24px", maxWidth: "520px", width: "100%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.18)",
        maxHeight: "90vh", overflowY: "auto",
      }}>
        {/* 헤더 */}
        <div style={{ marginBottom: "16px" }}>
          <p style={{ fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: "4px" }}>
            직접 조정 후 실제값 입력
          </p>
          <p style={{ fontSize: "0.875rem", color: colors.inkSecondary, lineHeight: 1.5 }}>
            <strong style={{ color: colors.inkPrimary }}>{action}</strong> 조정을 직접 수행하신 후,
            실제 적용한 환경값을 입력해 주세요.
          </p>
        </div>

        {/* 입력 그리드 */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: "12px",
          marginBottom: "16px",
        }}>
          {ENV_FIELDS.map(f => {
            const val    = values[f.key] ?? "";
            const hasErr = !!errors[f.key];
            const filled = val.trim() !== "";
            return (
              <div key={f.key}>
                <label style={{
                  display: "block", fontSize: "0.8rem", fontWeight: 600,
                  color: hasErr ? colors.dangerRed : colors.inkSecondary,
                  marginBottom: "4px",
                }}>
                  {f.label}
                  <span style={{ fontWeight: 400, color: colors.inkMuted, marginLeft: "3px" }}>({f.unit})</span>
                </label>
                <div style={{ position: "relative" }}>
                  <input
                    type="number" min={f.min} max={f.max} step={f.step}
                    value={val} placeholder={f.placeholder}
                    onChange={e => handleChange(f.key, e.target.value)}
                    style={{
                      width: "100%", boxSizing: "border-box",
                      padding: "8px 38px 8px 10px",
                      fontSize: "0.9375rem",
                      border: `1.5px solid ${hasErr ? colors.dangerRed : filled ? colors.chartwellBlue : colors.stoneBorder}`,
                      borderRadius: "8px", outline: "none",
                      background: colors.canvasFog, color: colors.inkPrimary,
                      minHeight: "40px",
                    }}
                  />
                  <span style={{
                    position: "absolute", right: "8px", top: "50%",
                    transform: "translateY(-50%)",
                    fontSize: "0.7rem", color: colors.inkMuted, pointerEvents: "none",
                  }}>{f.unit}</span>
                </div>
                {hasErr && (
                  <p style={{ fontSize: "0.72rem", color: colors.dangerRed, marginTop: "2px" }}>
                    {errors[f.key]}
                  </p>
                )}
              </div>
            );
          })}
        </div>

        {/* 안내 */}
        <p style={{ fontSize: "0.78rem", color: colors.inkMuted, marginBottom: "14px", lineHeight: 1.5 }}>
          * 일부만 입력해도 저장됩니다. 빈 항목은 이전 값이 유지됩니다.
          입력된 값은 AI 추천 재계산에 즉시 반영됩니다.
        </p>

        {/* API 에러 */}
        {apiErr && (
          <div style={{
            background: colors.dangerBg, color: colors.dangerRed,
            borderRadius: "8px", padding: "8px 12px",
            fontSize: "0.85rem", marginBottom: "12px",
          }}>{apiErr}</div>
        )}

        {/* 버튼 */}
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            onClick={handleSave}
            disabled={saving || filledCount === 0}
            style={{
              flex: 1,
              background: (saving || filledCount === 0) ? colors.inkMuted : colors.chartwellBlue,
              color: colors.cloudWhite, border: "none",
              borderRadius: radius.button, padding: "12px",
              fontSize: "0.9375rem", fontWeight: 700,
              cursor: (saving || filledCount === 0) ? "not-allowed" : "pointer",
              minHeight: "44px", transition: "background 200ms",
            }}
          >
            {saving ? "저장 중..." : `적용 완료 (${filledCount}개 입력)`}
          </button>
          <button
            onClick={onCancel}
            style={{
              flex: 1, background: colors.surfaceMuted, color: colors.inkPrimary,
              border: "none", borderRadius: radius.button, padding: "12px",
              fontSize: "0.9375rem", fontWeight: 600, cursor: "pointer", minHeight: "44px",
            }}
          >취소</button>
        </div>
      </div>
    </div>
  );
}

// ── 승인 모달 (반자동 티어 전용) ──────────────────────────────────────────────
function ApprovalModal({ action, onConfirm, onCancel }: {
  action: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div style={{
        background: colors.cloudWhite, borderRadius: radius.card,
        padding: "28px 24px", maxWidth: "360px", width: "90%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
      }}>
        <p style={{ fontSize: "1.125rem", fontWeight: 700, marginBottom: "8px" }}>적용 확인</p>
        <p style={{ fontSize: "1rem", color: colors.inkSecondary, marginBottom: "24px" }}>
          {action}을 실행하시겠습니까? 시스템이 자동으로 조정됩니다.
        </p>
        <div style={{ display: "flex", gap: "12px" }}>
          <button onClick={onConfirm} style={{
            flex: 1, background: colors.chartwellBlue, color: colors.cloudWhite,
            border: "none", borderRadius: radius.button, padding: "12px",
            fontSize: "1rem", fontWeight: 700, cursor: "pointer", minHeight: "44px",
          }}>실행</button>
          <button onClick={onCancel} style={{
            flex: 1, background: colors.surfaceMuted, color: colors.inkPrimary,
            border: "none", borderRadius: radius.button, padding: "12px",
            fontSize: "1rem", fontWeight: 600, cursor: "pointer", minHeight: "44px",
          }}>취소</button>
        </div>
      </div>
    </div>
  );
}

// ── 공통: 적용 버튼 훅 ────────────────────────────────────────────────────────
function useApply(rank: number, tier_action: Recommendation["tier_action"], onApply: (rank: number, confirmed: boolean) => Promise<void>) {
  const [loading, setLoading]         = useState(false);
  const [showModal, setShowModal]     = useState(false);       // approval_required
  const [showManual, setShowManual]   = useState(false);       // checklist
  const [done, setDone]               = useState(false);

  async function apply(confirmed: boolean) {
    setLoading(true);
    setShowModal(false);
    setShowManual(false);
    await onApply(rank, confirmed);
    setLoading(false);
    setDone(true);
  }

  function handleClick() {
    if (tier_action === "approval_required") setShowModal(true);
    else if (tier_action === "auto")         apply(true);
    else                                     setShowManual(true); // checklist → 직접 입력
  }

  return { loading, showModal, showManual, done, handleClick, apply, setShowModal, setShowManual };
}

// ── 수익 증분 포맷 ─────────────────────────────────────────────────────────────
function formatProfit(delta: number): string {
  const manwon = Math.round(delta / 10000);
  return manwon >= 0 ? `+${manwon}만원` : `${manwon}만원`;
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface Props {
  farmId: string;
  recommendation: Recommendation;
  onApply: (rank: number, confirmed: boolean) => Promise<void>;
}

interface MinorProps {
  farmId: string;
  recommendation: Recommendation;
  onApply: (rank: number, confirmed: boolean) => Promise<void>;
}

// ── 1순위 히어로 카드 ──────────────────────────────────────────────────────────
export function HeroRecommendation({ farmId, recommendation: rec, onApply }: Props) {
  const { loading, showModal, showManual, done, handleClick, apply, setShowModal, setShowManual } =
    useApply(rec.rank, rec.tier_action, onApply);

  const profitPositive = rec.profit_delta >= 0;
  const profitColor    = profitPositive ? colors.successGreen : colors.dangerRed;
  const profitBg       = profitPositive ? colors.successBg    : colors.dangerBg;

  const applyLabel =
    rec.tier_action === "auto"              ? "지금 적용" :
    rec.tier_action === "approval_required" ? "승인 후 적용" : "직접 적용";

  return (
    <div style={{
      background: colors.cloudWhite,
      borderRadius: radius.card,
      boxShadow: shadow.card,
      padding: "24px",
      border: `1px solid ${colors.stoneBorder}`,
    }}>
      {/* Label */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={colors.chartwellBlue} strokeWidth="2.5">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
        </svg>
        <span style={{ fontSize: "0.75rem", fontWeight: 600, color: colors.chartwellBlue, letterSpacing: "0.05em", textTransform: "uppercase" }}>
          AI 1순위 추천
        </span>
        {rec.tier_action === "checklist" && (
          <span style={{
            fontSize: "0.7rem", fontWeight: 600,
            background: colors.warningBg, color: colors.warningAmber,
            borderRadius: "999px", padding: "2px 8px",
          }}>수동 적용</span>
        )}
      </div>

      {/* Action */}
      <p style={{ fontSize: "1.125rem", fontWeight: 700, color: colors.inkPrimary, marginBottom: "8px", lineHeight: 1.4 }}>
        {rec.action_ko}
      </p>

      {/* Profit badge */}
      <div style={{ display: "inline-flex", alignItems: "center", gap: "6px", background: profitBg, borderRadius: radius.badge, padding: "6px 14px", marginBottom: "20px" }}>
        <span style={{ fontSize: "1.5rem", fontWeight: 800, color: profitColor }}>
          {formatProfit(rec.profit_delta)}
        </span>
        <span style={{ fontSize: "0.875rem", color: profitColor }}>예상 수익 증가</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        {!done ? (
          <button
            onClick={handleClick}
            disabled={loading}
            style={{
              background: loading ? colors.inkMuted : colors.chartwellBlue,
              color: colors.cloudWhite, border: "none",
              borderRadius: radius.button, padding: "12px 28px",
              fontSize: "1rem", fontWeight: 700,
              cursor: loading ? "not-allowed" : "pointer",
              minHeight: "44px", transition: "background 200ms",
            }}
          >
            {loading ? "처리 중..." : applyLabel}
          </button>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: "6px", color: colors.successGreen, fontWeight: 600 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M20 6L9 17l-5-5" />
            </svg>
            완료
          </div>
        )}
        <span style={{ fontSize: "0.875rem", color: colors.inkSecondary }}>
          신뢰도 {Math.round(rec.confidence * 100)}%
        </span>
      </div>

      {/* 수동 적용 모달 */}
      {showManual && (
        <ManualApplyModal
          farmId={farmId}
          action={rec.action_ko}
          onConfirm={() => apply(false)}
          onCancel={() => setShowManual(false)}
        />
      )}

      {/* 승인 모달 */}
      {showModal && (
        <ApprovalModal
          action={rec.action_ko}
          onConfirm={() => apply(true)}
          onCancel={() => setShowModal(false)}
        />
      )}
    </div>
  );
}

// ── 2~5순위 미니 추천 카드 ────────────────────────────────────────────────────
export function MinorRecommendation({ farmId, recommendation: rec, onApply }: MinorProps) {
  const { loading, showModal, showManual, done, handleClick, apply, setShowModal, setShowManual } =
    useApply(rec.rank, rec.tier_action, onApply);

  const profitPositive = rec.profit_delta >= 0;
  const profitColor    = profitPositive ? colors.successGreen : colors.dangerRed;

  const applyLabel =
    rec.tier_action === "auto"              ? "자동 적용" :
    rec.tier_action === "approval_required" ? "승인 후 적용" : "직접 적용";

  return (
    <div style={{
      background: colors.cloudWhite,
      borderRadius: radius.card,
      boxShadow: shadow.card,
      border: `1px solid ${colors.stoneBorder}`,
      padding: "14px 16px",
      display: "flex", alignItems: "center", gap: "12px",
    }}>
      {/* 순위 뱃지 */}
      <span style={{
        flexShrink: 0, fontSize: "0.7rem", fontWeight: 700,
        color: colors.chartwellBlue, background: colors.chartwellBlueBg,
        borderRadius: "999px", padding: "3px 9px", letterSpacing: "0.03em",
      }}>
        {rec.rank}순위
      </span>

      {/* 액션 텍스트 */}
      <span style={{ flex: 1, fontSize: "0.9375rem", fontWeight: 600, color: colors.inkPrimary, lineHeight: 1.35 }}>
        {rec.action_ko}
      </span>

      {/* 수익 증분 */}
      <span style={{
        flexShrink: 0, fontSize: "0.9375rem", fontWeight: 800,
        color: profitColor, minWidth: "60px", textAlign: "right",
      }}>
        {profitPositive ? "+" : ""}{Math.round(rec.profit_delta / 10000)}만원
      </span>

      {/* 적용 버튼 or 완료 */}
      {done ? (
        <div style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: "4px", color: colors.successGreen, fontWeight: 600, fontSize: "0.85rem" }}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M20 6L9 17l-5-5" />
          </svg>
          완료
        </div>
      ) : (
        <button
          onClick={handleClick}
          disabled={loading}
          title={applyLabel}
          style={{
            flexShrink: 0,
            background: loading ? colors.inkMuted : colors.chartwellBlue,
            color: colors.cloudWhite, border: "none",
            borderRadius: radius.button, padding: "8px 16px",
            fontSize: "0.85rem", fontWeight: 700,
            cursor: loading ? "not-allowed" : "pointer",
            minHeight: "36px", transition: "background 200ms", whiteSpace: "nowrap",
          }}
        >
          {loading ? "처리 중" : "적용"}
        </button>
      )}

      {/* 수동 적용 모달 */}
      {showManual && (
        <ManualApplyModal
          farmId={farmId}
          action={rec.action_ko}
          onConfirm={() => apply(false)}
          onCancel={() => setShowManual(false)}
        />
      )}

      {/* 승인 모달 */}
      {showModal && (
        <ApprovalModal
          action={rec.action_ko}
          onConfirm={() => apply(true)}
          onCancel={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
