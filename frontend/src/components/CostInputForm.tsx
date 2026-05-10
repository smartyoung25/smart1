import { useState } from "react";
import { colors, radius, shadow } from "../design-system/tokens";

// ── Types ──────────────────────────────────────────────────────────────────────

interface ManualCostInput {
  electricity_kwh_month?: number;
  electricity_rate?: number;
  water_m3_month?: number;
  water_rate?: number;
  heating_kwh_month?: number;
  heating_rate?: number;
  labor_hours_month?: number;
  labor_rate?: number;
  nutrients_krw_month?: number;
  pesticides_krw_month?: number;
}

interface CostInputFormProps {
  farmId: string;
  initialValues?: ManualCostInput | null;
  onSaved: () => void;       // 저장 완료 후 부모에서 costs 재로드
  onCancel?: () => void;
}

// ── 항목 정의 ─────────────────────────────────────────────────────────────────

interface FieldDef {
  category: string;
  icon: string;
  label: string;
  fields: {
    key: keyof ManualCostInput;
    placeholder: string;
    unit: string;
    defaultNote: string;     // 기본값 안내
    max: number;
  }[];
  directCost?: boolean;      // 사용량×단가 아닌 직접 금액 입력
}

const FIELD_DEFS: FieldDef[] = [
  {
    category: "electricity", icon: "⚡", label: "전기료",
    fields: [
      { key: "electricity_kwh_month", placeholder: "예: 2700", unit: "kWh/월",  defaultNote: "고지서 사용량", max: 100_000 },
      { key: "electricity_rate",      placeholder: "예: 105",   unit: "원/kWh", defaultNote: "농업용 기본 105원", max: 1_000 },
    ],
  },
  {
    category: "water", icon: "💧", label: "용수비",
    fields: [
      { key: "water_m3_month", placeholder: "예: 54",  unit: "m³/월",  defaultNote: "수도계량기 월 사용량", max: 10_000 },
      { key: "water_rate",     placeholder: "예: 700", unit: "원/m³",  defaultNote: "농업용 기본 700원", max: 10_000 },
    ],
  },
  {
    category: "heating", icon: "🔥", label: "난방비",
    fields: [
      { key: "heating_kwh_month", placeholder: "예: 1620",  unit: "kWh/월",  defaultNote: "가스 열량 환산치", max: 100_000 },
      { key: "heating_rate",      placeholder: "예: 85",    unit: "원/kWh",  defaultNote: "가스 환산 기본 85원", max: 1_000 },
    ],
  },
  {
    category: "labor", icon: "👤", label: "인건비",
    fields: [
      { key: "labor_hours_month", placeholder: "예: 90",     unit: "시간/월", defaultNote: "월 총 작업시간", max: 1_000 },
      { key: "labor_rate",        placeholder: "예: 12000",  unit: "원/시간", defaultNote: "기본 12,000원", max: 100_000 },
    ],
  },
  {
    category: "nutrients", icon: "🌱", label: "영양제·비료",
    directCost: true,
    fields: [
      { key: "nutrients_krw_month", placeholder: "예: 270000", unit: "원/월", defaultNote: "한 달 구입 비용 합계", max: 10_000_000 },
    ],
  },
  {
    category: "pesticides", icon: "🧪", label: "농약·방제",
    directCost: true,
    fields: [
      { key: "pesticides_krw_month", placeholder: "예: 60000", unit: "원/월", defaultNote: "한 달 농약·방제 비용", max: 10_000_000 },
    ],
  },
];

// ── 계산 미리보기 ──────────────────────────────────────────────────────────────

function calcPreview(values: ManualCostInput): number {
  const e = (values.electricity_kwh_month ?? 0) * (values.electricity_rate ?? 105);
  const w = (values.water_m3_month ?? 0)        * (values.water_rate ?? 700);
  const h = (values.heating_kwh_month ?? 0)     * (values.heating_rate ?? 85);
  const l = (values.labor_hours_month ?? 0)     * (values.labor_rate ?? 12_000);
  const n = values.nutrients_krw_month ?? 0;
  const p = values.pesticides_krw_month ?? 0;
  return e + w + h + l + n + p;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CostInputForm({ farmId, initialValues, onSaved, onCancel }: CostInputFormProps) {
  const [values,  setValues]  = useState<ManualCostInput>(initialValues ?? {});
  const [errors,  setErrors]  = useState<Partial<Record<keyof ManualCostInput, string>>>({});
  const [saving,  setSaving]  = useState(false);
  const [success, setSuccess] = useState(false);
  const [resetting, setResetting] = useState(false);

  // ── 유효성 검사 ──────────────────────────────────────────────────────────
  function validate(): boolean {
    const errs: typeof errors = {};
    FIELD_DEFS.forEach(def => {
      def.fields.forEach(f => {
        const v = values[f.key];
        if (v !== undefined && v !== null) {
          if (isNaN(Number(v)) || Number(v) < 0)      errs[f.key] = "0 이상의 숫자를 입력하세요";
          else if (Number(v) > f.max)                  errs[f.key] = `최대 ${f.max.toLocaleString()}까지 입력 가능`;
        }
      });
    });
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  // ── 저장 ─────────────────────────────────────────────────────────────────
  async function handleSave() {
    if (!validate()) return;

    // 빈 문자열 필드 제외, 숫자로 변환
    const payload: ManualCostInput = {};
    (Object.keys(values) as (keyof ManualCostInput)[]).forEach(k => {
      const v = values[k];
      if (v !== undefined && v !== null && String(v).trim() !== "") {
        payload[k] = Number(v);
      }
    });

    if (Object.keys(payload).length === 0) {
      alert("최소 한 항목 이상 입력해 주세요.");
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`/api/farms/${farmId}/costs/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      setSuccess(true);
      setTimeout(() => { setSuccess(false); onSaved(); }, 1000);
    } catch (e) {
      alert("저장 중 오류가 발생했습니다.");
    } finally {
      setSaving(false);
    }
  }

  // ── 기본값 복원 ───────────────────────────────────────────────────────────
  async function handleReset() {
    if (!confirm("입력한 실제값을 삭제하고 기본 추정값으로 되돌릴까요?")) return;
    setResetting(true);
    try {
      await fetch(`/api/farms/${farmId}/costs/manual`, { method: "DELETE" });
      setValues({});
      onSaved();
    } finally {
      setResetting(false);
    }
  }

  // ── 입력 핸들러 ───────────────────────────────────────────────────────────
  function handleChange(key: keyof ManualCostInput, raw: string) {
    setValues(prev => ({ ...prev, [key]: raw === "" ? undefined : raw }));
    if (errors[key]) setErrors(prev => { const n = { ...prev }; delete n[key]; return n; });
  }

  const preview = calcPreview(
    Object.fromEntries(
      Object.entries(values).map(([k, v]) => [k, v !== undefined ? Number(v) : undefined])
    ) as ManualCostInput
  );

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{
      background: colors.cloudWhite,
      border: `1.5px solid ${colors.chartwellBlue}`,
      borderRadius: radius.card,
      padding: "24px",
      boxShadow: shadow.card,
    }}>
      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }}>
        <div>
          <h3 style={{ fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: "3px" }}>
            실제 비용 직접 입력
          </h3>
          <p style={{ fontSize: "0.8125rem", color: colors.inkMuted }}>
            고지서·영수증을 참고해 실제 사용량과 단가를 입력하세요. 미입력 항목은 기본 추정값이 유지됩니다.
          </p>
        </div>
        {onCancel && (
          <button onClick={onCancel} style={{
            background: "none", border: "none", cursor: "pointer",
            color: colors.inkMuted, fontSize: "0.8rem", padding: "4px 8px",
          }}>
            닫기 ✕
          </button>
        )}
      </div>

      {/* 항목별 입력 그리드 */}
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        {FIELD_DEFS.map(def => (
          <div key={def.category}>
            {/* 카테고리 레이블 */}
            <div style={{
              display: "flex", alignItems: "center", gap: "8px",
              marginBottom: "10px",
              paddingBottom: "8px",
              borderBottom: `1px solid ${colors.stoneBorder}`,
            }}>
              <span style={{ fontSize: "1rem" }}>{def.icon}</span>
              <span style={{ fontWeight: 700, fontSize: "0.9375rem", color: colors.inkPrimary }}>
                {def.label}
              </span>
              {def.directCost && (
                <span style={{
                  fontSize: "0.65rem", background: colors.surfaceMuted,
                  color: colors.inkMuted, borderRadius: radius.badge,
                  padding: "2px 7px", fontWeight: 600,
                }}>
                  직접 금액 입력
                </span>
              )}
            </div>

            {/* 필드 행 */}
            <div style={{
              display: "grid",
              gridTemplateColumns: def.fields.length === 2 ? "1fr 1fr" : "1fr",
              gap: "12px",
            }}>
              {def.fields.map(f => {
                const hasErr = !!errors[f.key];
                const val = values[f.key];
                // 계산 미리보기 (2개 필드인 경우)
                let rowTotal: number | null = null;
                if (!def.directCost && def.fields.length === 2) {
                  const f0 = def.fields[0].key;
                  const f1 = def.fields[1].key;
                  const v0 = values[f0];
                  const v1 = values[f1];
                  if (v0 !== undefined && v1 !== undefined && String(v0) !== "" && String(v1) !== "") {
                    rowTotal = Number(v0) * Number(v1);
                  }
                }

                return (
                  <div key={String(f.key)}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "5px" }}>
                      <label style={{ fontSize: "0.8125rem", fontWeight: 600, color: colors.inkSecondary }}>
                        {f.unit}
                      </label>
                      <span style={{ fontSize: "0.7rem", color: colors.inkMuted }}>{f.defaultNote}</span>
                    </div>
                    <div style={{ position: "relative" }}>
                      <input
                        type="number"
                        value={val ?? ""}
                        onChange={e => handleChange(f.key, e.target.value)}
                        placeholder={f.placeholder}
                        min={0}
                        max={f.max}
                        step="any"
                        style={{
                          width: "100%",
                          padding: "10px 50px 10px 14px",
                          border: `1.5px solid ${hasErr ? colors.dangerRed : colors.stoneBorder}`,
                          borderRadius: radius.input,
                          fontSize: "1rem",
                          color: colors.inkPrimary,
                          background: colors.canvasFog,
                          outline: "none",
                        }}
                      />
                      <span style={{
                        position: "absolute", right: "12px", top: "50%",
                        transform: "translateY(-50%)",
                        fontSize: "0.72rem", color: colors.inkMuted, pointerEvents: "none",
                      }}>
                        {f.unit.split("/")[1] ?? f.unit}
                      </span>
                    </div>
                    {hasErr && (
                      <p style={{ fontSize: "0.72rem", color: colors.dangerRed, marginTop: "4px" }}>
                        {errors[f.key]}
                      </p>
                    )}
                    {/* 계산 미리보기 — 두 번째 필드(단가) 아래 표시 */}
                    {rowTotal !== null && f.key === def.fields[1].key && (
                      <p style={{ fontSize: "0.75rem", color: colors.chartwellBlue, marginTop: "4px", fontWeight: 600 }}>
                        = {Math.round(rowTotal).toLocaleString()}원/월
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 합계 미리보기 */}
      {preview > 0 && (
        <div style={{
          marginTop: "20px",
          padding: "14px 16px",
          background: colors.chartwellBlueBg,
          borderRadius: "8px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontSize: "0.875rem", fontWeight: 600, color: colors.chartwellBlue }}>
            입력값 기준 월 예상 총 비용
          </span>
          <span style={{ fontSize: "1.25rem", fontWeight: 800, color: colors.chartwellBlue }}>
            {Math.round(preview / 10_000).toLocaleString()}만원
          </span>
        </div>
      )}

      {/* 버튼 행 */}
      <div style={{ display: "flex", gap: "10px", marginTop: "20px", flexWrap: "wrap" }}>
        <button
          onClick={handleSave}
          disabled={saving || success}
          style={{
            flex: 1, minWidth: "140px",
            background: success ? colors.successGreen : colors.chartwellBlue,
            color: "#fff", border: "none",
            borderRadius: radius.button,
            padding: "13px 20px",
            fontSize: "1rem", fontWeight: 700,
            cursor: saving || success ? "default" : "pointer",
            transition: "background 200ms",
          }}
        >
          {success ? "✓ 저장 완료" : saving ? "저장 중..." : "실제값 저장"}
        </button>

        {initialValues && Object.keys(initialValues).length > 0 && (
          <button
            onClick={handleReset}
            disabled={resetting}
            style={{
              background: colors.dangerBg, color: colors.dangerRed,
              border: `1.5px solid ${colors.dangerRed}`,
              borderRadius: radius.button,
              padding: "13px 18px",
              fontSize: "0.9rem", fontWeight: 700,
              cursor: resetting ? "default" : "pointer",
            }}
          >
            {resetting ? "초기화 중..." : "기본값으로 복원"}
          </button>
        )}

        {onCancel && (
          <button
            onClick={onCancel}
            style={{
              background: "none", color: colors.inkSecondary,
              border: `1.5px solid ${colors.stoneBorder}`,
              borderRadius: radius.button,
              padding: "13px 18px",
              fontSize: "0.9rem", fontWeight: 600,
              cursor: "pointer",
            }}
          >
            취소
          </button>
        )}
      </div>
    </div>
  );
}
