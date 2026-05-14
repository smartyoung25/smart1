import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
// ── 수동 적용 모달 (체크리스트 티어 전용) ──────────────────────────────────────
function ManualApplyModal({ farmId, action, onConfirm, onCancel }) {
    const [values, setValues] = useState({});
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [apiErr, setApiErr] = useState(null);
    function handleChange(key, raw) {
        setValues(p => ({ ...p, [key]: raw }));
        setErrors(p => ({ ...p, [key]: "" }));
        setApiErr(null);
    }
    function validate() {
        const next = {};
        let ok = true;
        for (const f of ENV_FIELDS) {
            const raw = (values[f.key] ?? "").trim();
            if (!raw)
                continue;
            const num = parseFloat(raw);
            if (isNaN(num)) {
                next[f.key] = "숫자를 입력해 주세요";
                ok = false;
            }
            else if (num < f.min || num > f.max) {
                next[f.key] = `${f.min}~${f.max} ${f.unit}`;
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
            const raw = (values[f.key] ?? "").trim();
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
            onConfirm();
        }
        catch (e) {
            setApiErr(e instanceof Error ? e.message : "저장에 실패했습니다.");
        }
        finally {
            setSaving(false);
        }
    }
    const filledCount = ENV_FIELDS.filter(f => (values[f.key] ?? "").trim() !== "").length;
    return (_jsx("div", { style: {
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
            display: "flex", alignItems: "center", justifyContent: "center",
            zIndex: 100, padding: "16px",
        }, children: _jsxs("div", { style: {
                background: colors.cloudWhite, borderRadius: radius.card,
                padding: "24px", maxWidth: "520px", width: "100%",
                boxShadow: "0 20px 60px rgba(0,0,0,0.18)",
                maxHeight: "90vh", overflowY: "auto",
            }, children: [_jsxs("div", { style: { marginBottom: "16px" }, children: [_jsx("p", { style: { fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: "4px" }, children: "\uC9C1\uC811 \uC870\uC815 \uD6C4 \uC2E4\uC81C\uAC12 \uC785\uB825" }), _jsxs("p", { style: { fontSize: "0.875rem", color: colors.inkSecondary, lineHeight: 1.5 }, children: [_jsx("strong", { style: { color: colors.inkPrimary }, children: action }), " \uC870\uC815\uC744 \uC9C1\uC811 \uC218\uD589\uD558\uC2E0 \uD6C4, \uC2E4\uC81C \uC801\uC6A9\uD55C \uD658\uACBD\uAC12\uC744 \uC785\uB825\uD574 \uC8FC\uC138\uC694."] })] }), _jsx("div", { style: {
                        display: "grid",
                        gridTemplateColumns: "repeat(2, 1fr)",
                        gap: "12px",
                        marginBottom: "16px",
                    }, children: ENV_FIELDS.map(f => {
                        const val = values[f.key] ?? "";
                        const hasErr = !!errors[f.key];
                        const filled = val.trim() !== "";
                        return (_jsxs("div", { children: [_jsxs("label", { style: {
                                        display: "block", fontSize: "0.8rem", fontWeight: 600,
                                        color: hasErr ? colors.dangerRed : colors.inkSecondary,
                                        marginBottom: "4px",
                                    }, children: [f.label, _jsxs("span", { style: { fontWeight: 400, color: colors.inkMuted, marginLeft: "3px" }, children: ["(", f.unit, ")"] })] }), _jsxs("div", { style: { position: "relative" }, children: [_jsx("input", { type: "number", min: f.min, max: f.max, step: f.step, value: val, placeholder: f.placeholder, onChange: e => handleChange(f.key, e.target.value), style: {
                                                width: "100%", boxSizing: "border-box",
                                                padding: "8px 38px 8px 10px",
                                                fontSize: "0.9375rem",
                                                border: `1.5px solid ${hasErr ? colors.dangerRed : filled ? colors.chartwellBlue : colors.stoneBorder}`,
                                                borderRadius: "8px", outline: "none",
                                                background: colors.canvasFog, color: colors.inkPrimary,
                                                minHeight: "40px",
                                            } }), _jsx("span", { style: {
                                                position: "absolute", right: "8px", top: "50%",
                                                transform: "translateY(-50%)",
                                                fontSize: "0.7rem", color: colors.inkMuted, pointerEvents: "none",
                                            }, children: f.unit })] }), hasErr && (_jsx("p", { style: { fontSize: "0.72rem", color: colors.dangerRed, marginTop: "2px" }, children: errors[f.key] }))] }, f.key));
                    }) }), _jsx("p", { style: { fontSize: "0.78rem", color: colors.inkMuted, marginBottom: "14px", lineHeight: 1.5 }, children: "* \uC77C\uBD80\uB9CC \uC785\uB825\uD574\uB3C4 \uC800\uC7A5\uB429\uB2C8\uB2E4. \uBE48 \uD56D\uBAA9\uC740 \uC774\uC804 \uAC12\uC774 \uC720\uC9C0\uB429\uB2C8\uB2E4. \uC785\uB825\uB41C \uAC12\uC740 AI \uCD94\uCC9C \uC7AC\uACC4\uC0B0\uC5D0 \uC989\uC2DC \uBC18\uC601\uB429\uB2C8\uB2E4." }), apiErr && (_jsx("div", { style: {
                        background: colors.dangerBg, color: colors.dangerRed,
                        borderRadius: "8px", padding: "8px 12px",
                        fontSize: "0.85rem", marginBottom: "12px",
                    }, children: apiErr })), _jsxs("div", { style: { display: "flex", gap: "10px" }, children: [_jsx("button", { onClick: handleSave, disabled: saving || filledCount === 0, style: {
                                flex: 1,
                                background: (saving || filledCount === 0) ? colors.inkMuted : colors.chartwellBlue,
                                color: colors.cloudWhite, border: "none",
                                borderRadius: radius.button, padding: "12px",
                                fontSize: "0.9375rem", fontWeight: 700,
                                cursor: (saving || filledCount === 0) ? "not-allowed" : "pointer",
                                minHeight: "44px", transition: "background 200ms",
                            }, children: saving ? "저장 중..." : `적용 완료 (${filledCount}개 입력)` }), _jsx("button", { onClick: onCancel, style: {
                                flex: 1, background: colors.surfaceMuted, color: colors.inkPrimary,
                                border: "none", borderRadius: radius.button, padding: "12px",
                                fontSize: "0.9375rem", fontWeight: 600, cursor: "pointer", minHeight: "44px",
                            }, children: "\uCDE8\uC18C" })] })] }) }));
}
// ── 승인 모달 (반자동 티어 전용) ──────────────────────────────────────────────
function ApprovalModal({ action, onConfirm, onCancel }) {
    return (_jsx("div", { style: {
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
        }, children: _jsxs("div", { style: {
                background: colors.cloudWhite, borderRadius: radius.card,
                padding: "28px 24px", maxWidth: "360px", width: "90%",
                boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
            }, children: [_jsx("p", { style: { fontSize: "1.125rem", fontWeight: 700, marginBottom: "8px" }, children: "\uC801\uC6A9 \uD655\uC778" }), _jsxs("p", { style: { fontSize: "1rem", color: colors.inkSecondary, marginBottom: "24px" }, children: [action, "\uC744 \uC2E4\uD589\uD558\uC2DC\uACA0\uC2B5\uB2C8\uAE4C? \uC2DC\uC2A4\uD15C\uC774 \uC790\uB3D9\uC73C\uB85C \uC870\uC815\uB429\uB2C8\uB2E4."] }), _jsxs("div", { style: { display: "flex", gap: "12px" }, children: [_jsx("button", { onClick: onConfirm, style: {
                                flex: 1, background: colors.chartwellBlue, color: colors.cloudWhite,
                                border: "none", borderRadius: radius.button, padding: "12px",
                                fontSize: "1rem", fontWeight: 700, cursor: "pointer", minHeight: "44px",
                            }, children: "\uC2E4\uD589" }), _jsx("button", { onClick: onCancel, style: {
                                flex: 1, background: colors.surfaceMuted, color: colors.inkPrimary,
                                border: "none", borderRadius: radius.button, padding: "12px",
                                fontSize: "1rem", fontWeight: 600, cursor: "pointer", minHeight: "44px",
                            }, children: "\uCDE8\uC18C" })] })] }) }));
}
// ── 공통: 적용 버튼 훅 ────────────────────────────────────────────────────────
function useApply(rank, tier_action, onApply) {
    const [loading, setLoading] = useState(false);
    const [showModal, setShowModal] = useState(false); // approval_required
    const [showManual, setShowManual] = useState(false); // checklist
    const [done, setDone] = useState(false);
    async function apply(confirmed) {
        setLoading(true);
        setShowModal(false);
        setShowManual(false);
        await onApply(rank, confirmed);
        setLoading(false);
        setDone(true);
    }
    function handleClick() {
        if (tier_action === "approval_required")
            setShowModal(true);
        else if (tier_action === "auto")
            apply(true);
        else
            setShowManual(true); // checklist → 직접 입력
    }
    return { loading, showModal, showManual, done, handleClick, apply, setShowModal, setShowManual };
}
// ── 수익 증분 포맷 ─────────────────────────────────────────────────────────────
function formatProfit(delta) {
    const manwon = Math.round(delta / 10000);
    return manwon >= 0 ? `+${manwon}만원` : `${manwon}만원`;
}
// ── 1순위 히어로 카드 ──────────────────────────────────────────────────────────
export function HeroRecommendation({ farmId, recommendation: rec, onApply }) {
    const { loading, showModal, showManual, done, handleClick, apply, setShowModal, setShowManual } = useApply(rec.rank, rec.tier_action, onApply);
    const profitPositive = rec.profit_delta >= 0;
    const profitColor = profitPositive ? colors.successGreen : colors.dangerRed;
    const profitBg = profitPositive ? colors.successBg : colors.dangerBg;
    const applyLabel = rec.tier_action === "auto" ? "지금 적용" :
        rec.tier_action === "approval_required" ? "승인 후 적용" : "직접 적용";
    return (_jsxs("div", { style: {
            background: colors.cloudWhite,
            borderRadius: radius.card,
            boxShadow: shadow.card,
            padding: "24px",
            border: `1px solid ${colors.stoneBorder}`,
        }, children: [_jsxs("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }, children: [_jsx("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: colors.chartwellBlue, strokeWidth: "2.5", children: _jsx("path", { d: "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" }) }), _jsx("span", { style: { fontSize: "0.75rem", fontWeight: 600, color: colors.chartwellBlue, letterSpacing: "0.05em", textTransform: "uppercase" }, children: "AI 1\uC21C\uC704 \uCD94\uCC9C" }), rec.tier_action === "checklist" && (_jsx("span", { style: {
                            fontSize: "0.7rem", fontWeight: 600,
                            background: colors.warningBg, color: colors.warningAmber,
                            borderRadius: "999px", padding: "2px 8px",
                        }, children: "\uC218\uB3D9 \uC801\uC6A9" }))] }), _jsx("p", { style: { fontSize: "1.125rem", fontWeight: 700, color: colors.inkPrimary, marginBottom: "8px", lineHeight: 1.4 }, children: rec.action_ko }), _jsxs("div", { style: { display: "inline-flex", alignItems: "center", gap: "6px", background: profitBg, borderRadius: radius.badge, padding: "6px 14px", marginBottom: "20px" }, children: [_jsx("span", { style: { fontSize: "1.5rem", fontWeight: 800, color: profitColor }, children: formatProfit(rec.profit_delta) }), _jsx("span", { style: { fontSize: "0.875rem", color: profitColor }, children: "\uC608\uC0C1 \uC218\uC775 \uC99D\uAC00" })] }), _jsxs("div", { style: { display: "flex", alignItems: "center", gap: "12px" }, children: [!done ? (_jsx("button", { onClick: handleClick, disabled: loading, style: {
                            background: loading ? colors.inkMuted : colors.chartwellBlue,
                            color: colors.cloudWhite, border: "none",
                            borderRadius: radius.button, padding: "12px 28px",
                            fontSize: "1rem", fontWeight: 700,
                            cursor: loading ? "not-allowed" : "pointer",
                            minHeight: "44px", transition: "background 200ms",
                        }, children: loading ? "처리 중..." : applyLabel })) : (_jsxs("div", { style: { display: "flex", alignItems: "center", gap: "6px", color: colors.successGreen, fontWeight: 600 }, children: [_jsx("svg", { width: "18", height: "18", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", children: _jsx("path", { d: "M20 6L9 17l-5-5" }) }), "\uC644\uB8CC"] })), _jsxs("span", { style: { fontSize: "0.875rem", color: colors.inkSecondary }, children: ["\uC2E0\uB8B0\uB3C4 ", Math.round(rec.confidence * 100), "%"] })] }), showManual && (_jsx(ManualApplyModal, { farmId: farmId, action: rec.action_ko, onConfirm: () => apply(false), onCancel: () => setShowManual(false) })), showModal && (_jsx(ApprovalModal, { action: rec.action_ko, onConfirm: () => apply(true), onCancel: () => setShowModal(false) }))] }));
}
// ── 2~5순위 미니 추천 카드 ────────────────────────────────────────────────────
export function MinorRecommendation({ farmId, recommendation: rec, onApply }) {
    const { loading, showModal, showManual, done, handleClick, apply, setShowModal, setShowManual } = useApply(rec.rank, rec.tier_action, onApply);
    const profitPositive = rec.profit_delta >= 0;
    const profitColor = profitPositive ? colors.successGreen : colors.dangerRed;
    const applyLabel = rec.tier_action === "auto" ? "자동 적용" :
        rec.tier_action === "approval_required" ? "승인 후 적용" : "직접 적용";
    return (_jsxs("div", { style: {
            background: colors.cloudWhite,
            borderRadius: radius.card,
            boxShadow: shadow.card,
            border: `1px solid ${colors.stoneBorder}`,
            padding: "14px 16px",
            display: "flex", alignItems: "center", gap: "12px",
        }, children: [_jsxs("span", { style: {
                    flexShrink: 0, fontSize: "0.7rem", fontWeight: 700,
                    color: colors.chartwellBlue, background: colors.chartwellBlueBg,
                    borderRadius: "999px", padding: "3px 9px", letterSpacing: "0.03em",
                }, children: [rec.rank, "\uC21C\uC704"] }), _jsx("span", { style: { flex: 1, fontSize: "0.9375rem", fontWeight: 600, color: colors.inkPrimary, lineHeight: 1.35 }, children: rec.action_ko }), _jsxs("span", { style: {
                    flexShrink: 0, fontSize: "0.9375rem", fontWeight: 800,
                    color: profitColor, minWidth: "60px", textAlign: "right",
                }, children: [profitPositive ? "+" : "", Math.round(rec.profit_delta / 10000), "\uB9CC\uC6D0"] }), done ? (_jsxs("div", { style: { flexShrink: 0, display: "flex", alignItems: "center", gap: "4px", color: colors.successGreen, fontWeight: 600, fontSize: "0.85rem" }, children: [_jsx("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", children: _jsx("path", { d: "M20 6L9 17l-5-5" }) }), "\uC644\uB8CC"] })) : (_jsx("button", { onClick: handleClick, disabled: loading, title: applyLabel, style: {
                    flexShrink: 0,
                    background: loading ? colors.inkMuted : colors.chartwellBlue,
                    color: colors.cloudWhite, border: "none",
                    borderRadius: radius.button, padding: "8px 16px",
                    fontSize: "0.85rem", fontWeight: 700,
                    cursor: loading ? "not-allowed" : "pointer",
                    minHeight: "36px", transition: "background 200ms", whiteSpace: "nowrap",
                }, children: loading ? "처리 중" : "적용" })), showManual && (_jsx(ManualApplyModal, { farmId: farmId, action: rec.action_ko, onConfirm: () => apply(false), onCancel: () => setShowManual(false) })), showModal && (_jsx(ApprovalModal, { action: rec.action_ko, onConfirm: () => apply(true), onCancel: () => setShowModal(false) }))] }));
}
