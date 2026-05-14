import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
/**
 * ManualEnvInput — IoT 미구축 농가(farm_005 등)의 환경값 수동 입력 폼
 *
 * 저장 후 onSaved() 콜백으로 부모에게 알려 추천 재조회를 유도한다.
 */
import { useState } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
const ENV_FIELDS = [
    { key: "temp_internal", label: "내부 온도", unit: "°C", min: 0, max: 50, step: 0.1, placeholder: "예: 22.5" },
    { key: "humidity_int", label: "내부 습도", unit: "%", min: 20, max: 100, step: 1, placeholder: "예: 75" },
    { key: "co2_ppm", label: "CO₂ 농도", unit: "ppm", min: 300, max: 2000, step: 10, placeholder: "예: 900" },
    { key: "solar_rad", label: "일사량", unit: "W/m²", min: 0, max: 1200, step: 10, placeholder: "예: 350" },
    { key: "ec_dsm", label: "EC (양액)", unit: "dS/m", min: 0.5, max: 5.0, step: 0.1, placeholder: "예: 2.1" },
    { key: "soil_temp", label: "지온", unit: "°C", min: 5, max: 35, step: 0.1, placeholder: "예: 18.0" },
];
// ── Component ──────────────────────────────────────────────────────────────
export function ManualEnvInput({ farmId, storedValues, onSaved }) {
    const initial = {};
    ENV_FIELDS.forEach((f) => {
        initial[f.key] = storedValues?.[f.key] != null ? String(storedValues[f.key]) : "";
    });
    const [values, setValues] = useState(initial);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [apiErr, setApiErr] = useState(null);
    function handleChange(key, raw) {
        setValues((prev) => ({ ...prev, [key]: raw }));
        setErrors((prev) => ({ ...prev, [key]: "" }));
        setSaved(false);
        setApiErr(null);
    }
    function validate() {
        const next = {};
        let ok = true;
        for (const f of ENV_FIELDS) {
            const raw = values[f.key].trim();
            if (!raw)
                continue; // 빈 필드는 허용 (부분 입력 가능)
            const num = parseFloat(raw);
            if (isNaN(num)) {
                next[f.key] = "숫자를 입력해 주세요";
                ok = false;
            }
            else if (num < f.min || num > f.max) {
                next[f.key] = `${f.min} ~ ${f.max} ${f.unit} 범위여야 합니다`;
                ok = false;
            }
        }
        setErrors(next);
        return ok;
    }
    async function handleSave() {
        if (!validate())
            return;
        const payload = {};
        for (const f of ENV_FIELDS) {
            const raw = values[f.key].trim();
            if (raw !== "")
                payload[f.key] = parseFloat(raw);
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
            setSaved(true);
            onSaved(payload);
        }
        catch (e) {
            setApiErr(e instanceof Error ? e.message : "저장에 실패했습니다.");
        }
        finally {
            setSaving(false);
        }
    }
    const filledCount = ENV_FIELDS.filter((f) => values[f.key].trim() !== "").length;
    return (_jsxs("div", { style: {
            background: colors.cloudWhite,
            borderRadius: radius.card,
            boxShadow: shadow.card,
            border: `1px solid ${colors.stoneBorder}`,
            overflow: "hidden",
        }, children: [_jsxs("div", { style: {
                    background: colors.warningBg,
                    borderBottom: `1px solid ${colors.stoneBorder}`,
                    padding: "16px 20px",
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                }, children: [_jsxs("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: colors.warningAmber, strokeWidth: "2.5", children: [_jsx("path", { d: "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" }), _jsx("line", { x1: "12", y1: "9", x2: "12", y2: "13" }), _jsx("line", { x1: "12", y1: "17", x2: "12.01", y2: "17" })] }), _jsxs("div", { children: [_jsx("p", { style: { fontWeight: 700, fontSize: "0.9375rem", color: colors.inkPrimary }, children: "IoT \uBBF8\uAD6C\uCD95 \uB18D\uAC00 \u2014 \uD658\uACBD\uAC12 \uC9C1\uC811 \uC785\uB825" }), _jsx("p", { style: { fontSize: "0.8125rem", color: colors.inkSecondary, marginTop: "2px" }, children: "\uC13C\uC11C \uB370\uC774\uD130\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4. \uD604\uC7AC \uB18D\uC7A5 \uC0C1\uD0DC\uB97C \uC9C1\uC811 \uC785\uB825\uD558\uBA74 AI \uCD94\uCC9C\uC774 \uD65C\uC131\uD654\uB429\uB2C8\uB2E4." })] })] }), _jsxs("div", { style: { padding: "20px" }, children: [_jsx("div", { style: {
                            display: "grid",
                            gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
                            gap: "16px",
                            marginBottom: "20px",
                        }, children: ENV_FIELDS.map((f) => {
                            const hasErr = !!errors[f.key];
                            const val = values[f.key];
                            const filled = val.trim() !== "";
                            return (_jsxs("div", { children: [_jsxs("label", { style: {
                                            display: "block",
                                            fontSize: "0.875rem",
                                            fontWeight: 600,
                                            color: hasErr ? colors.dangerRed : colors.inkPrimary,
                                            marginBottom: "6px",
                                        }, children: [f.label, _jsxs("span", { style: { fontWeight: 400, color: colors.inkMuted, marginLeft: "4px" }, children: ["(", f.unit, ")"] })] }), _jsxs("div", { style: { position: "relative" }, children: [_jsx("input", { type: "number", min: f.min, max: f.max, step: f.step, value: val, placeholder: f.placeholder, onChange: (e) => handleChange(f.key, e.target.value), style: {
                                                    width: "100%",
                                                    padding: "10px 48px 10px 14px",
                                                    fontSize: "1rem",
                                                    border: `1.5px solid ${hasErr ? colors.dangerRed : filled ? colors.chartwellBlue : colors.stoneBorder}`,
                                                    borderRadius: "8px",
                                                    outline: "none",
                                                    background: colors.canvasFog,
                                                    color: colors.inkPrimary,
                                                    minHeight: "44px",
                                                    boxSizing: "border-box",
                                                } }), _jsx("span", { style: {
                                                    position: "absolute", right: "12px", top: "50%",
                                                    transform: "translateY(-50%)",
                                                    fontSize: "0.75rem", color: colors.inkMuted, pointerEvents: "none",
                                                }, children: f.unit })] }), hasErr && (_jsx("p", { style: { fontSize: "0.75rem", color: colors.dangerRed, marginTop: "4px" }, children: errors[f.key] })), _jsxs("p", { style: { fontSize: "0.7rem", color: colors.inkMuted, marginTop: "3px" }, children: ["\uBC94\uC704: ", f.min, " ~ ", f.max] })] }, f.key));
                        }) }), apiErr && (_jsx("div", { style: {
                            background: colors.dangerBg, color: colors.dangerRed,
                            borderRadius: "8px", padding: "10px 14px",
                            fontSize: "0.875rem", marginBottom: "16px",
                        }, children: apiErr })), _jsxs("div", { style: { display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }, children: [_jsx("button", { onClick: handleSave, disabled: saving || filledCount === 0, style: {
                                    background: (saving || filledCount === 0) ? colors.inkMuted : colors.chartwellBlue,
                                    color: colors.cloudWhite,
                                    border: "none",
                                    borderRadius: radius.button,
                                    padding: "12px 28px",
                                    fontSize: "1rem",
                                    fontWeight: 700,
                                    cursor: (saving || filledCount === 0) ? "not-allowed" : "pointer",
                                    minHeight: "44px",
                                    transition: "background 200ms",
                                }, children: saving ? "저장 중..." : "저장 후 AI 추천 받기" }), saved && (_jsxs("div", { style: { display: "flex", alignItems: "center", gap: "6px", color: colors.successGreen, fontWeight: 600 }, children: [_jsx("svg", { width: "18", height: "18", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", children: _jsx("path", { d: "M20 6L9 17l-5-5" }) }), "\uC800\uC7A5 \uC644\uB8CC \u2014 AI\uCD94\uCC9C \uD0ED\uC744 \uD655\uC778\uD558\uC138\uC694"] })), _jsxs("span", { style: { fontSize: "0.8125rem", color: colors.inkMuted }, children: [filledCount, "/", ENV_FIELDS.length, "\uAC1C \uC785\uB825\uB428"] })] }), _jsx("p", { style: {
                            marginTop: "16px",
                            fontSize: "0.8rem",
                            color: colors.inkMuted,
                            lineHeight: 1.6,
                        }, children: "* \uC77C\uBD80 \uD56D\uBAA9\uB9CC \uC785\uB825\uD574\uB3C4 \uC800\uC7A5 \uAC00\uB2A5\uD569\uB2C8\uB2E4. \uBE48 \uD56D\uBAA9\uC740 \uC9C0\uC5ED \uD3C9\uADE0\uAC12\uC73C\uB85C \uBCF4\uC644\uB429\uB2C8\uB2E4." })] })] }));
}
