import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
const FIELD_DEFS = [
    {
        category: "electricity", icon: "⚡", label: "전기료",
        fields: [
            { key: "electricity_kwh_month", placeholder: "예: 2700", unit: "kWh/월", defaultNote: "고지서 사용량", max: 100000 },
            { key: "electricity_rate", placeholder: "예: 105", unit: "원/kWh", defaultNote: "농업용 기본 105원", max: 1000 },
        ],
    },
    {
        category: "water", icon: "💧", label: "용수비",
        fields: [
            { key: "water_m3_month", placeholder: "예: 54", unit: "m³/월", defaultNote: "수도계량기 월 사용량", max: 10000 },
            { key: "water_rate", placeholder: "예: 700", unit: "원/m³", defaultNote: "농업용 기본 700원", max: 10000 },
        ],
    },
    {
        category: "heating", icon: "🔥", label: "난방비",
        fields: [
            { key: "heating_kwh_month", placeholder: "예: 1620", unit: "kWh/월", defaultNote: "가스 열량 환산치", max: 100000 },
            { key: "heating_rate", placeholder: "예: 85", unit: "원/kWh", defaultNote: "가스 환산 기본 85원", max: 1000 },
        ],
    },
    {
        category: "labor", icon: "👤", label: "인건비",
        fields: [
            { key: "labor_hours_month", placeholder: "예: 90", unit: "시간/월", defaultNote: "월 총 작업시간", max: 1000 },
            { key: "labor_rate", placeholder: "예: 12000", unit: "원/시간", defaultNote: "기본 12,000원", max: 100000 },
        ],
    },
    {
        category: "nutrients", icon: "🌱", label: "영양제·비료",
        directCost: true,
        fields: [
            { key: "nutrients_krw_month", placeholder: "예: 270000", unit: "원/월", defaultNote: "한 달 구입 비용 합계", max: 10000000 },
        ],
    },
    {
        category: "pesticides", icon: "🧪", label: "농약·방제",
        directCost: true,
        fields: [
            { key: "pesticides_krw_month", placeholder: "예: 60000", unit: "원/월", defaultNote: "한 달 농약·방제 비용", max: 10000000 },
        ],
    },
];
// ── 계산 미리보기 ──────────────────────────────────────────────────────────────
function calcPreview(values) {
    const e = (values.electricity_kwh_month ?? 0) * (values.electricity_rate ?? 105);
    const w = (values.water_m3_month ?? 0) * (values.water_rate ?? 700);
    const h = (values.heating_kwh_month ?? 0) * (values.heating_rate ?? 85);
    const l = (values.labor_hours_month ?? 0) * (values.labor_rate ?? 12000);
    const n = values.nutrients_krw_month ?? 0;
    const p = values.pesticides_krw_month ?? 0;
    return e + w + h + l + n + p;
}
// ── Component ─────────────────────────────────────────────────────────────────
export function CostInputForm({ farmId, initialValues, onSaved, onCancel }) {
    const [values, setValues] = useState(initialValues ?? {});
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [success, setSuccess] = useState(false);
    const [resetting, setResetting] = useState(false);
    // ── 유효성 검사 ──────────────────────────────────────────────────────────
    function validate() {
        const errs = {};
        FIELD_DEFS.forEach(def => {
            def.fields.forEach(f => {
                const v = values[f.key];
                if (v !== undefined && v !== null) {
                    if (isNaN(Number(v)) || Number(v) < 0)
                        errs[f.key] = "0 이상의 숫자를 입력하세요";
                    else if (Number(v) > f.max)
                        errs[f.key] = `최대 ${f.max.toLocaleString()}까지 입력 가능`;
                }
            });
        });
        setErrors(errs);
        return Object.keys(errs).length === 0;
    }
    // ── 저장 ─────────────────────────────────────────────────────────────────
    async function handleSave() {
        if (!validate())
            return;
        // 빈 문자열 필드 제외, 숫자로 변환
        const payload = {};
        Object.keys(values).forEach(k => {
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
            if (!res.ok)
                throw new Error(await res.text());
            setSuccess(true);
            setTimeout(() => { setSuccess(false); onSaved(); }, 1000);
        }
        catch (e) {
            alert("저장 중 오류가 발생했습니다.");
        }
        finally {
            setSaving(false);
        }
    }
    // ── 기본값 복원 ───────────────────────────────────────────────────────────
    async function handleReset() {
        if (!confirm("입력한 실제값을 삭제하고 기본 추정값으로 되돌릴까요?"))
            return;
        setResetting(true);
        try {
            await fetch(`/api/farms/${farmId}/costs/manual`, { method: "DELETE" });
            setValues({});
            onSaved();
        }
        finally {
            setResetting(false);
        }
    }
    // ── 입력 핸들러 ───────────────────────────────────────────────────────────
    function handleChange(key, raw) {
        setValues(prev => ({ ...prev, [key]: raw === "" ? undefined : raw }));
        if (errors[key])
            setErrors(prev => { const n = { ...prev }; delete n[key]; return n; });
    }
    const preview = calcPreview(Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v !== undefined ? Number(v) : undefined])));
    // ── Render ────────────────────────────────────────────────────────────────
    return (_jsxs("div", { style: {
            background: colors.cloudWhite,
            border: `1.5px solid ${colors.chartwellBlue}`,
            borderRadius: radius.card,
            padding: "24px",
            boxShadow: shadow.card,
        }, children: [_jsxs("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "20px" }, children: [_jsxs("div", { children: [_jsx("h3", { style: { fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: "3px" }, children: "\uC2E4\uC81C \uBE44\uC6A9 \uC9C1\uC811 \uC785\uB825" }), _jsx("p", { style: { fontSize: "0.8125rem", color: colors.inkMuted }, children: "\uACE0\uC9C0\uC11C\u00B7\uC601\uC218\uC99D\uC744 \uCC38\uACE0\uD574 \uC2E4\uC81C \uC0AC\uC6A9\uB7C9\uACFC \uB2E8\uAC00\uB97C \uC785\uB825\uD558\uC138\uC694. \uBBF8\uC785\uB825 \uD56D\uBAA9\uC740 \uAE30\uBCF8 \uCD94\uC815\uAC12\uC774 \uC720\uC9C0\uB429\uB2C8\uB2E4." })] }), onCancel && (_jsx("button", { onClick: onCancel, style: {
                            background: "none", border: "none", cursor: "pointer",
                            color: colors.inkMuted, fontSize: "0.8rem", padding: "4px 8px",
                        }, children: "\uB2EB\uAE30 \u2715" }))] }), _jsx("div", { style: { display: "flex", flexDirection: "column", gap: "20px" }, children: FIELD_DEFS.map(def => (_jsxs("div", { children: [_jsxs("div", { style: {
                                display: "flex", alignItems: "center", gap: "8px",
                                marginBottom: "10px",
                                paddingBottom: "8px",
                                borderBottom: `1px solid ${colors.stoneBorder}`,
                            }, children: [_jsx("span", { style: { fontSize: "1rem" }, children: def.icon }), _jsx("span", { style: { fontWeight: 700, fontSize: "0.9375rem", color: colors.inkPrimary }, children: def.label }), def.directCost && (_jsx("span", { style: {
                                        fontSize: "0.65rem", background: colors.surfaceMuted,
                                        color: colors.inkMuted, borderRadius: radius.badge,
                                        padding: "2px 7px", fontWeight: 600,
                                    }, children: "\uC9C1\uC811 \uAE08\uC561 \uC785\uB825" }))] }), _jsx("div", { style: {
                                display: "grid",
                                gridTemplateColumns: def.fields.length === 2 ? "1fr 1fr" : "1fr",
                                gap: "12px",
                            }, children: def.fields.map(f => {
                                const hasErr = !!errors[f.key];
                                const val = values[f.key];
                                // 계산 미리보기 (2개 필드인 경우)
                                let rowTotal = null;
                                if (!def.directCost && def.fields.length === 2) {
                                    const f0 = def.fields[0].key;
                                    const f1 = def.fields[1].key;
                                    const v0 = values[f0];
                                    const v1 = values[f1];
                                    if (v0 !== undefined && v1 !== undefined && String(v0) !== "" && String(v1) !== "") {
                                        rowTotal = Number(v0) * Number(v1);
                                    }
                                }
                                return (_jsxs("div", { children: [_jsxs("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "5px" }, children: [_jsx("label", { style: { fontSize: "0.8125rem", fontWeight: 600, color: colors.inkSecondary }, children: f.unit }), _jsx("span", { style: { fontSize: "0.7rem", color: colors.inkMuted }, children: f.defaultNote })] }), _jsxs("div", { style: { position: "relative" }, children: [_jsx("input", { type: "number", value: val ?? "", onChange: e => handleChange(f.key, e.target.value), placeholder: f.placeholder, min: 0, max: f.max, step: "any", style: {
                                                        width: "100%",
                                                        padding: "10px 50px 10px 14px",
                                                        border: `1.5px solid ${hasErr ? colors.dangerRed : colors.stoneBorder}`,
                                                        borderRadius: radius.input,
                                                        fontSize: "1rem",
                                                        color: colors.inkPrimary,
                                                        background: colors.canvasFog,
                                                        outline: "none",
                                                    } }), _jsx("span", { style: {
                                                        position: "absolute", right: "12px", top: "50%",
                                                        transform: "translateY(-50%)",
                                                        fontSize: "0.72rem", color: colors.inkMuted, pointerEvents: "none",
                                                    }, children: f.unit.split("/")[1] ?? f.unit })] }), hasErr && (_jsx("p", { style: { fontSize: "0.72rem", color: colors.dangerRed, marginTop: "4px" }, children: errors[f.key] })), rowTotal !== null && f.key === def.fields[1].key && (_jsxs("p", { style: { fontSize: "0.75rem", color: colors.chartwellBlue, marginTop: "4px", fontWeight: 600 }, children: ["= ", Math.round(rowTotal).toLocaleString(), "\uC6D0/\uC6D4"] }))] }, String(f.key)));
                            }) })] }, def.category))) }), preview > 0 && (_jsxs("div", { style: {
                    marginTop: "20px",
                    padding: "14px 16px",
                    background: colors.chartwellBlueBg,
                    borderRadius: "8px",
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                }, children: [_jsx("span", { style: { fontSize: "0.875rem", fontWeight: 600, color: colors.chartwellBlue }, children: "\uC785\uB825\uAC12 \uAE30\uC900 \uC6D4 \uC608\uC0C1 \uCD1D \uBE44\uC6A9" }), _jsxs("span", { style: { fontSize: "1.25rem", fontWeight: 800, color: colors.chartwellBlue }, children: [Math.round(preview / 10000).toLocaleString(), "\uB9CC\uC6D0"] })] })), _jsxs("div", { style: { display: "flex", gap: "10px", marginTop: "20px", flexWrap: "wrap" }, children: [_jsx("button", { onClick: handleSave, disabled: saving || success, style: {
                            flex: 1, minWidth: "140px",
                            background: success ? colors.successGreen : colors.chartwellBlue,
                            color: "#fff", border: "none",
                            borderRadius: radius.button,
                            padding: "13px 20px",
                            fontSize: "1rem", fontWeight: 700,
                            cursor: saving || success ? "default" : "pointer",
                            transition: "background 200ms",
                        }, children: success ? "✓ 저장 완료" : saving ? "저장 중..." : "실제값 저장" }), initialValues && Object.keys(initialValues).length > 0 && (_jsx("button", { onClick: handleReset, disabled: resetting, style: {
                            background: colors.dangerBg, color: colors.dangerRed,
                            border: `1.5px solid ${colors.dangerRed}`,
                            borderRadius: radius.button,
                            padding: "13px 18px",
                            fontSize: "0.9rem", fontWeight: 700,
                            cursor: resetting ? "default" : "pointer",
                        }, children: resetting ? "초기화 중..." : "기본값으로 복원" })), onCancel && (_jsx("button", { onClick: onCancel, style: {
                            background: "none", color: colors.inkSecondary,
                            border: `1.5px solid ${colors.stoneBorder}`,
                            borderRadius: radius.button,
                            padding: "13px 18px",
                            fontSize: "0.9rem", fontWeight: 600,
                            cursor: "pointer",
                        }, children: "\uCDE8\uC18C" }))] })] }));
}
