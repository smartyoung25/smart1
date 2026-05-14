import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState, useEffect, useCallback, useRef } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
import { HeroRecommendation, MinorRecommendation } from "../components/HeroRecommendation";
import { AiChat } from "../components/AiChat";
import { CostInputForm } from "../components/CostInputForm";
import { FarmSettings } from "../components/FarmSettings";
// ── Fetch helper ──────────────────────────────────────────────────────────────
async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok)
        throw new Error(`API ${url} → ${res.status}`);
    return res.json();
}
// ── 관측소 번호 → 지점명 ──────────────────────────────────────────────────────
const STATION_NAMES = {
    101: "춘천", 105: "강릉", 108: "서울", 112: "인천", 114: "원주",
    119: "수원", 127: "충주", 129: "서산", 131: "청주", 133: "천안",
    136: "안동", 137: "상주", 138: "포항", 140: "군산", 143: "대구",
    146: "전주", 152: "울산", 155: "창원", 156: "광주", 159: "부산",
    168: "순천", 177: "논산", 184: "제주", 189: "서귀포", 192: "진주",
    202: "여주", 203: "파주", 212: "홍천", 221: "평창", 243: "부안",
    244: "고창", 247: "남원", 261: "해남", 271: "영주", 288: "밀양",
    289: "보령",
};
// ── 관측소 배너 컴포넌트 ────────────────────────────────────────────────────────
function StationBanner({ stationId, sido, sigungu }) {
    if (!stationId)
        return null;
    const name = STATION_NAMES[stationId] ?? `${stationId}번`;
    const location = [sido, sigungu].filter(Boolean).join(" ") || name;
    return (_jsxs("div", { style: {
            display: "flex", alignItems: "center", gap: "8px",
            padding: "8px 14px",
            background: "#f0f9ff",
            border: "1px solid #bae6fd",
            borderRadius: "8px",
            marginBottom: "12px",
            fontSize: "0.8rem",
            color: "#0369a1",
        }, children: [_jsx("span", { children: "\uD83C\uDF24\uFE0F" }), _jsxs("span", { children: ["\uAE30\uC0C1\uCCAD ASOS ", _jsxs("strong", { children: [name, "(", stationId, ")"] }), " \uAD00\uCE21\uC18C \uC5F0\uACB0", location !== name && _jsxs("span", { style: { color: "#64748b", marginLeft: 6 }, children: ["\u2014 ", location] })] })] }));
}
// ── 환경 변수 한글 레이블 ─────────────────────────────────────────────────────
const ENV_LABELS = {
    temp_internal: "내부 온도",
    temp_external: "외부 온도",
    humidity_int: "내부 습도",
    humidity_ext: "외부 습도",
    co2_ppm: "CO₂ 농도",
    solar_rad: "일사량",
    solar_rad_est: "추정 일사량",
    ec_dsm: "EC (양액)",
    soil_temp: "지온",
    wind_speed_ext: "풍속",
};
const ENV_INPUT_FIELDS = [
    { key: "temp_internal", label: "내부 온도", unit: "°C", min: 0, max: 50, step: 0.1, placeholder: "예: 22.5" },
    { key: "humidity_int", label: "내부 습도", unit: "%", min: 20, max: 100, step: 1, placeholder: "예: 75" },
    { key: "co2_ppm", label: "CO₂ 농도", unit: "ppm", min: 300, max: 2000, step: 10, placeholder: "예: 900" },
    { key: "solar_rad", label: "일사량", unit: "W/m²", min: 0, max: 1200, step: 10, placeholder: "예: 350" },
    { key: "ec_dsm", label: "EC (양액)", unit: "dS/m", min: 0.5, max: 5.0, step: 0.1, placeholder: "예: 2.1" },
    { key: "soil_temp", label: "지온", unit: "°C", min: 5, max: 35, step: 0.1, placeholder: "예: 18.0" },
];
// ── 측정값 그리드 (실내/실외 공용) ───────────────────────────────────────────
function EnvValueGrid({ measurements }) {
    if (!measurements.length)
        return null;
    return (_jsx("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }, children: measurements.map(pt => (_jsxs("div", { style: {
                background: "#f8fafc", borderRadius: radius.input,
                padding: "10px 12px",
                display: "flex", flexDirection: "column", gap: "2px",
            }, children: [_jsx("span", { style: { fontSize: "0.72rem", color: colors.inkMuted, fontWeight: 500 }, children: ENV_LABELS[pt.canonical_name] ?? pt.canonical_name }), _jsxs("span", { style: { fontSize: "1.1rem", fontWeight: 600, color: colors.inkPrimary }, children: [pt.value.toLocaleString("ko-KR", { maximumFractionDigits: 1 }), _jsx("span", { style: { fontSize: "0.75rem", fontWeight: 400, color: colors.inkMuted, marginLeft: 3 }, children: pt.unit })] }), pt.imputed && (_jsx("span", { style: { fontSize: "0.65rem", color: colors.chartwellBlue }, children: "\uCD94\uC815\uAC12" }))] }, pt.canonical_name))) }));
}
// ── 실내 환경 수동 입력 인라인 폼 ────────────────────────────────────────────
function InlineEnvForm({ farmId, storedValues, onSaved, onCancel }) {
    const init = {};
    ENV_INPUT_FIELDS.forEach(f => {
        init[f.key] = storedValues?.[f.key] != null ? String(storedValues[f.key]) : "";
    });
    const [vals, setVals] = useState(init);
    const [errors, setErrors] = useState({});
    const [saving, setSaving] = useState(false);
    const [apiErr, setApiErr] = useState(null);
    function handleChange(key, raw) {
        setVals(p => ({ ...p, [key]: raw }));
        setErrors(p => ({ ...p, [key]: "" }));
        setApiErr(null);
    }
    function validate() {
        const next = {};
        let ok = true;
        for (const f of ENV_INPUT_FIELDS) {
            const raw = vals[f.key].trim();
            if (!raw)
                continue;
            const num = parseFloat(raw);
            if (isNaN(num)) {
                next[f.key] = "숫자를 입력해주세요";
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
        for (const f of ENV_INPUT_FIELDS) {
            const raw = vals[f.key].trim();
            if (raw)
                payload[f.key] = parseFloat(raw);
        }
        if (!Object.keys(payload).length) {
            setApiErr("최소 하나 이상의 값을 입력해 주세요.");
            return;
        }
        setSaving(true);
        try {
            const res = await fetch(`/api/farms/${farmId}/environment/manual`, {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!res.ok)
                throw new Error(await res.text());
            onSaved(payload);
        }
        catch (e) {
            setApiErr(e instanceof Error ? e.message : "저장에 실패했습니다.");
        }
        finally {
            setSaving(false);
        }
    }
    return (_jsxs("div", { children: [_jsx("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", marginBottom: "12px" }, children: ENV_INPUT_FIELDS.map(f => (_jsxs("div", { children: [_jsxs("label", { style: { display: "block", fontSize: "0.72rem", color: colors.inkMuted, fontWeight: 500, marginBottom: 4 }, children: [f.label, " ", _jsxs("span", { style: { color: colors.inkMuted }, children: ["(", f.unit, ")"] })] }), _jsx("input", { type: "number", inputMode: "decimal", min: f.min, max: f.max, step: f.step, placeholder: f.placeholder, value: vals[f.key], onChange: e => handleChange(f.key, e.target.value), style: {
                                width: "100%", padding: "8px 10px", fontSize: "0.9rem",
                                border: `1.5px solid ${errors[f.key] ? colors.dangerRed : "#e2e8f0"}`,
                                borderRadius: radius.input, outline: "none",
                                background: "#fff", boxSizing: "border-box",
                            } }), errors[f.key] && (_jsx("span", { style: { fontSize: "0.68rem", color: colors.dangerRed }, children: errors[f.key] }))] }, f.key))) }), apiErr && _jsx("p", { style: { fontSize: "0.8rem", color: colors.dangerRed, marginBottom: 8 }, children: apiErr }), _jsxs("div", { style: { display: "flex", gap: "8px" }, children: [_jsx("button", { onClick: handleSave, disabled: saving, style: {
                            flex: 1, padding: "10px", borderRadius: "9999px", border: "none",
                            background: saving ? "#94a3b8" : colors.chartwellBlue,
                            color: "#fff", fontWeight: 600, fontSize: "0.9rem", cursor: saving ? "not-allowed" : "pointer",
                        }, children: saving ? "저장 중..." : "저장" }), _jsx("button", { onClick: onCancel, style: {
                            padding: "10px 16px", borderRadius: "9999px",
                            border: "1.5px solid #e2e8f0", background: "#fff",
                            color: colors.inkMuted, fontSize: "0.9rem", cursor: "pointer",
                        }, children: "\uCDE8\uC18C" })] })] }));
}
// ── 실내·외부 환경 2패널 ─────────────────────────────────────────────────────
function EnvTwoPanel({ envData, farmId, manualValues, onSaved }) {
    const [editMode, setEditMode] = useState(false);
    if (!envData)
        return (_jsx("div", { style: { textAlign: "center", padding: "40px", color: colors.inkMuted }, children: "\uD658\uACBD \uB370\uC774\uD130\uB97C \uBD88\uB7EC\uC624\uB294 \uC911\uC785\uB2C8\uB2E4. \uC7A0\uC2DC \uD6C4 \uB2E4\uC2DC \uC2DC\uB3C4\uD574 \uC8FC\uC138\uC694." }));
    const { indoor, outdoor } = envData;
    const isEditable = indoor.editable;
    const hasIndoor = indoor.has_data && indoor.measurements.length > 0;
    const hasOutdoor = outdoor.has_data && outdoor.measurements.length > 0;
    function handleSaved(v) {
        setEditMode(false);
        onSaved(v);
    }
    const sourceBadge = (source) => {
        const conf = {
            iot: { label: "IoT 센서", color: colors.successGreen, bg: "#f0fdf4" },
            manual_input: { label: "수동 입력", color: colors.warningAmber, bg: "#fffbeb" },
            asos: { label: "기상청", color: colors.chartwellBlue, bg: "#eff6ff" },
            none: { label: "미입력", color: colors.inkMuted, bg: "#f1f5f9" },
        };
        const c = conf[source] ?? conf.none;
        return (_jsx("span", { style: {
                fontSize: "0.68rem", fontWeight: 600, padding: "2px 8px",
                borderRadius: "9999px", background: c.bg, color: c.color,
                marginLeft: 6,
            }, children: c.label }));
    };
    const panelStyle = {
        background: "#fff", borderRadius: radius.card,
        boxShadow: shadow.card, padding: "16px",
        display: "flex", flexDirection: "column", gap: "14px",
    };
    const headerStyle = {
        display: "flex", alignItems: "center", justifyContent: "space-between",
    };
    const titleStyle = {
        fontSize: "0.9rem", fontWeight: 700, color: colors.inkPrimary,
        display: "flex", alignItems: "center",
    };
    const editBtnStyle = {
        fontSize: "0.78rem", fontWeight: 600, padding: "5px 14px",
        borderRadius: "9999px", border: `1.5px solid ${colors.chartwellBlue}`,
        background: "#fff", color: colors.chartwellBlue, cursor: "pointer",
    };
    return (_jsxs("div", { style: {
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: "14px",
        }, children: [_jsxs("div", { style: panelStyle, children: [_jsxs("div", { style: headerStyle, children: [_jsxs("span", { style: titleStyle, children: ["\uC2E4\uB0B4 \uD658\uACBD", sourceBadge(indoor.source)] }), isEditable && !editMode && (_jsx("button", { style: editBtnStyle, onClick: () => setEditMode(true), children: hasIndoor ? "수정" : "입력하기" })), isEditable && editMode && (_jsx("button", { onClick: () => setEditMode(false), style: {
                                    ...editBtnStyle,
                                    border: "1.5px solid #e2e8f0", color: colors.inkMuted,
                                }, children: "\uCDE8\uC18C" }))] }), editMode ? (_jsx(InlineEnvForm, { farmId: farmId, storedValues: manualValues, onSaved: handleSaved, onCancel: () => setEditMode(false) })) : hasIndoor ? (_jsx(EnvValueGrid, { measurements: indoor.measurements })) : (_jsxs("div", { style: {
                            textAlign: "center", padding: "24px 12px",
                            background: "#f8fafc", borderRadius: radius.input,
                        }, children: [_jsx("div", { style: { fontSize: "1.6rem", marginBottom: 8 }, children: "\uD83D\uDCCB" }), _jsxs("p", { style: { fontSize: "0.85rem", color: colors.inkMuted, marginBottom: 12 }, children: ["\uC544\uC9C1 \uC2E4\uB0B4 \uD658\uACBD\uAC12\uC774 \uC5C6\uC2B5\uB2C8\uB2E4.", _jsx("br", {}), "\uD604\uC7AC \uB18D\uC7A5 \uC0C1\uD0DC\uB97C \uC9C1\uC811 \uC785\uB825\uD558\uBA74 AI \uCD94\uCC9C \uC815\uD655\uB3C4\uAC00 \uB192\uC544\uC9D1\uB2C8\uB2E4."] }), _jsx("button", { style: {
                                    ...editBtnStyle,
                                    background: colors.chartwellBlue, color: "#fff", border: "none",
                                }, onClick: () => setEditMode(true), children: "\uC9C0\uAE08 \uC785\uB825\uD558\uAE30" })] }))] }), _jsxs("div", { style: panelStyle, children: [_jsxs("div", { style: headerStyle, children: [_jsxs("span", { style: titleStyle, children: ["\uC678\uBD80 \uAE30\uC0C1", sourceBadge(outdoor.source)] }), _jsx("span", { style: { fontSize: "0.72rem", color: colors.inkMuted }, children: "\uC2E4\uC2DC\uAC04 \u00B7 \uC790\uB3D9\uAC31\uC2E0" })] }), hasOutdoor ? (_jsx(EnvValueGrid, { measurements: outdoor.measurements })) : (_jsx("div", { style: {
                            textAlign: "center", padding: "24px 12px",
                            background: "#f8fafc", borderRadius: radius.input,
                        }, children: _jsx("p", { style: { fontSize: "0.85rem", color: colors.inkMuted }, children: "\uAE30\uC0C1\uCCAD ASOS \uB370\uC774\uD130\uB97C \uBD88\uB7EC\uC62C \uC218 \uC5C6\uC2B5\uB2C8\uB2E4." }) })), _jsx("div", { style: {
                            fontSize: "0.7rem", color: colors.inkMuted, padding: "8px 10px",
                            background: "#eff6ff", borderRadius: radius.input, lineHeight: 1.5,
                        }, children: "\uAE30\uC0C1\uCCAD ASOS \uAD00\uCE21\uC18C \uC2E4\uCE21\uAC12 \uAE30\uBC18. \uC628\uC2E4 \uB0B4\uBD80\uC640 \uC678\uBD80 \uD658\uACBD\uC740 \uCC28\uC774\uAC00 \uC788\uC744 \uC218 \uC788\uC2B5\uB2C8\uB2E4." })] })] }));
}
// ── 톱니바퀴 아이콘 SVG ────────────────────────────────────────────────────────
function GearIcon() {
    return (_jsxs("svg", { width: "15", height: "15", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2", strokeLinecap: "round", strokeLinejoin: "round", children: [_jsx("circle", { cx: "12", cy: "12", r: "3" }), _jsx("path", { d: "M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06\n               a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09\n               A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83\n               l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09\n               A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83\n               l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09\n               a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83\n               l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09\n               a1.65 1.65 0 0 0-1.51 1z" })] }));
}
// ── Constants ─────────────────────────────────────────────────────────────────
const SEVERITY_COLORS = {
    danger: { bg: colors.dangerBg, text: colors.dangerRed, border: colors.dangerRed },
    warning: { bg: colors.warningBg, text: colors.warningAmber, border: colors.warningAmber },
    info: { bg: colors.chartwellBlueBg, text: colors.chartwellBlue, border: colors.chartwellBlue },
};
const SEVERITY_LABEL = { danger: "위험", warning: "주의", info: "정보" };
const COST_ICONS = {
    electricity: "⚡", water: "💧", heating: "🔥",
    labor: "👤", nutrients: "🌱", pesticides: "🧪",
};
const TABS = [
    { key: "recommendations", label: "AI 추천" },
    { key: "environment", label: "환경" },
    { key: "harvest", label: "수확예측" },
    { key: "revenue", label: "수익" },
    { key: "costs", label: "비용분석" },
    { key: "chat", label: "AI 상담" },
];
// ── Component ─────────────────────────────────────────────────────────────────
export function FarmerDashboard({ farmId = "farm_001" }) {
    const [tab, setTab] = useState("recommendations");
    const [alertPanelOpen, setAlertPanelOpen] = useState(false);
    const [meta, setMeta] = useState(null);
    const [summary, setSummary] = useState(null);
    const [recs, setRecs] = useState([]);
    const [envData, setEnvData] = useState(null);
    const [revenue, setRevenue] = useState(null);
    const [costs, setCosts] = useState(null);
    const [harvest, setHarvest] = useState(null);
    const [loading, setLoading] = useState(true);
    const [manualValues, setManualValues] = useState(null);
    const [showCostInput, setShowCostInput] = useState(false);
    const [showFarmSettings, setShowFarmSettings] = useState(false);
    // ── Fetch ──────────────────────────────────────────────────────────────────
    useEffect(() => {
        setLoading(true);
        setRecs([]);
        setEnvData(null);
        setManualValues(null);
        setAlertPanelOpen(false);
        setShowCostInput(false);
        Promise.all([
            fetchJson(`/api/farms/${farmId}/meta`),
            fetchJson(`/api/farms/${farmId}/summary`),
        ]).then(([m, s]) => { setMeta(m); setSummary(s); })
            .catch(console.error).finally(() => setLoading(false));
    }, [farmId]);
    const refreshData = useCallback(() => {
        fetchJson(`/api/farms/${farmId}/recommendations`)
            .then(r => setRecs(r.recommendations)).catch(console.error);
        fetchJson(`/api/farms/${farmId}/environment`)
            .then(r => {
            setEnvData(r);
            // Pre-populate manualValues from stored indoor measurements so the
            // edit form is not blank when re-opening on an IoT-less farm.
            if (r.indoor.source === "manual_input" && r.indoor.measurements.length > 0) {
                const fromApi = {};
                r.indoor.measurements.forEach(pt => { fromApi[pt.canonical_name] = pt.value; });
                setManualValues(prev => ({ ...fromApi, ...(prev ?? {}) }));
            }
        })
            .catch(err => {
            console.error("[env fetch]", err);
            setEnvData(null);
        });
        fetchJson(`/api/farms/${farmId}/revenue`)
            .then(r => setRevenue(r)).catch(console.error);
        fetchJson(`/api/farms/${farmId}/costs`)
            .then(r => setCosts(r)).catch(console.error);
        fetchJson(`/api/farms/${farmId}/harvest`)
            .then(r => setHarvest(r)).catch(console.error);
    }, [farmId]);
    useEffect(() => { refreshData(); }, [refreshData]);
    // ── Handlers ───────────────────────────────────────────────────────────────
    function handleManualSaved(saved) {
        setManualValues(prev => ({ ...(prev ?? {}), ...saved }));
        refreshData();
    }
    async function handleApply(rank, confirmed) {
        await fetch(`/api/farms/${farmId}/apply`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rank, confirmed }),
        });
    }
    // ── Derived ────────────────────────────────────────────────────────────────
    const heroRec = recs[0] ?? null;
    const minorRecs = recs.slice(1);
    const isNoIot = meta !== null && !meta.iot_available;
    const alerts = summary?.alerts ?? [];
    const alertCount = alerts.length;
    // ── Tab content ────────────────────────────────────────────────────────────
    function renderContent() {
        if (loading)
            return (_jsx("div", { className: "loading-center", children: "\uBD88\uB7EC\uC624\uB294 \uC911..." }));
        switch (tab) {
            // ── AI 추천 ──────────────────────────────────────────────────────────
            case "recommendations": return (_jsxs("div", { className: "col-gap", children: [isNoIot && !envData?.indoor?.has_data && (_jsxs("div", { className: "warn-card", children: [_jsx(WarnIcon, {}), _jsxs("div", { children: [_jsx("p", { className: "warn-title", children: "\uD658\uACBD \uB370\uC774\uD130\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4" }), _jsxs("p", { className: "warn-body", children: ["AI \uCD94\uCC9C\uC744 \uBC1B\uC73C\uB824\uBA74", " ", _jsx("button", { className: "inline-link", onClick: () => setTab("environment"), children: "\uD658\uACBD \uD0ED" }), "\uC5D0\uC11C \uD604\uC7AC \uB18D\uC7A5 \uC0C1\uD0DC\uB97C \uC785\uB825\uD574 \uC8FC\uC138\uC694."] })] })] })), heroRec && _jsx(HeroRecommendation, { farmId: farmId, recommendation: heroRec, onApply: handleApply }), minorRecs.map(rec => (_jsx(MinorRecommendation, { farmId: farmId, recommendation: rec, onApply: handleApply }, rec.rank)))] }));
            // ── 환경 ─────────────────────────────────────────────────────────────
            case "environment": {
                // 현재 실내 환경값 flat dict (슬라이더 초기값용)
                const indoorFlat = {};
                envData?.indoor?.measurements?.forEach(pt => {
                    indoorFlat[pt.canonical_name] = pt.value;
                });
                // IoT 없는 농가는 저장된 manualValues 사용
                const currentEnvFlat = Object.keys(indoorFlat).length > 0
                    ? indoorFlat
                    : (manualValues ?? {});
                return (_jsxs("div", { className: "col-gap", children: [_jsx(StationBanner, { stationId: meta?.asos_station_id, sido: meta?.sido, sigungu: meta?.sigungu }), _jsx(EnvTwoPanel, { envData: envData, farmId: farmId, manualValues: manualValues, onSaved: handleManualSaved }), _jsx(WhatIfPanel, { farmId: farmId, currentEnv: currentEnvFlat })] }));
            }
            // ── 수확예측 ─────────────────────────────────────────────────────────
            case "harvest": return (_jsx(HarvestTab, { harvest: harvest, meta: meta }));
            // ── 수익 ─────────────────────────────────────────────────────────────
            case "revenue": return (_jsxs("div", { className: "col-gap", children: [_jsxs("div", { className: "card", children: [_jsxs("div", { className: "row-gap8 mb16", children: [_jsx("h2", { className: "section-title", children: "\uC218\uC775 \uD604\uD669" }), meta?.crop && _jsxs("span", { className: "muted-sm", children: ["\u2014 ", meta.crop] })] }), revenue ? (_jsx("div", { className: "kpi-grid", children: [
                                    { label: "KAMIS 단가", value: `${revenue.kamis_price_krw_kg.toLocaleString()}원/kg`, color: colors.inkPrimary },
                                    { label: "예상 매출", value: `${Math.round(revenue.predicted_revenue_krw / 10000).toLocaleString()}만원`, color: colors.chartwellBlue },
                                    { label: "예상 비용", value: `${Math.round(revenue.predicted_cost_krw / 10000).toLocaleString()}만원`, color: colors.warningAmber },
                                    { label: "예상 순이익", value: `${Math.round(revenue.predicted_profit_krw / 10000).toLocaleString()}만원`, color: colors.successGreen },
                                ].map(({ label, value, color }) => (_jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: label }), _jsx("p", { className: "kpi-value", style: { color }, children: value })] }, label))) })) : _jsx("p", { className: "muted-sm", children: "\uC218\uC775 \uB370\uC774\uD130\uB97C \uBD88\uB7EC\uC624\uB294 \uC911..." })] }), costs && (_jsxs("div", { className: "card", children: [_jsxs("div", { className: "row-gap8 mb16", children: [_jsx("h2", { className: "section-title", children: "\uC6D4 \uBE44\uC6A9 \uC694\uC57D" }), _jsx("button", { className: "inline-link", onClick: () => setTab("costs"), children: "\uC0C1\uC138 \uBCF4\uAE30 \u2192" })] }), _jsxs("div", { className: "kpi-grid", children: [_jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC6D4 \uCD1D \uBE44\uC6A9" }), _jsxs("p", { className: "kpi-value", style: { color: colors.warningAmber }, children: [Math.round(costs.total_cost_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "m\u00B2\uB2F9 \uBE44\uC6A9" }), _jsxs("p", { className: "kpi-value", children: [costs.cost_per_m2.toLocaleString(), "\uC6D0"] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC6D4 \uC804\uAE30 \uC0AC\uC6A9\uB7C9" }), _jsxs("p", { className: "kpi-value", children: [costs.electricity_kwh_month.toLocaleString(), "kWh"] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC6D4 \uC6A9\uC218 \uC0AC\uC6A9\uB7C9" }), _jsxs("p", { className: "kpi-value", children: [costs.water_m3_month.toLocaleString(), "m\u00B3"] })] })] })] }))] }));
            // ── 비용분석 ─────────────────────────────────────────────────────────
            case "costs": return (_jsxs("div", { className: "col-gap", children: [(isNoIot || showCostInput) ? (_jsx(CostInputForm, { farmId: farmId, initialValues: costs?.manual_input ?? null, onSaved: () => { setShowCostInput(false); refreshData(); }, onCancel: isNoIot ? undefined : () => setShowCostInput(false) })) : (_jsx("div", { style: { display: "flex", justifyContent: "flex-end" }, children: _jsx("button", { onClick: () => setShowCostInput(true), style: {
                                background: costs?.has_manual_input ? colors.chartwellBlueBg : colors.surfaceMuted,
                                color: costs?.has_manual_input ? colors.chartwellBlue : colors.inkSecondary,
                                border: `1.5px solid ${costs?.has_manual_input ? colors.chartwellBlue : colors.stoneBorder}`,
                                borderRadius: radius.button,
                                padding: "8px 16px",
                                fontSize: "0.875rem",
                                fontWeight: 600,
                                cursor: "pointer",
                            }, children: costs?.has_manual_input ? "✏️ 실제값 수정" : "✏️ 실제값 입력" }) })), costs ? (_jsxs(_Fragment, { children: [_jsxs("div", { className: "card", children: [_jsx("h2", { className: "section-title mb16", children: "\uC6D4 \uC6B4\uC601 \uBE44\uC6A9 \uBD84\uC11D" }), _jsxs("div", { className: "kpi-grid", children: [_jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC6D4 \uCD1D \uBE44\uC6A9" }), _jsxs("p", { className: "kpi-value", style: { color: colors.dangerRed }, children: [Math.round(costs.total_cost_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "m\u00B2\uB2F9 \uC6D4 \uBE44\uC6A9" }), _jsxs("p", { className: "kpi-value", children: [costs.cost_per_m2.toLocaleString(), "\uC6D0/m\u00B2"] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC6D4 \uC804\uAE30 \uC0AC\uC6A9" }), _jsxs("p", { className: "kpi-value", children: [costs.electricity_kwh_month.toLocaleString(), "kWh"] }), _jsxs("p", { className: "kpi-sub", children: ["\uD0C4\uC18C ", (costs.electricity_kwh_month * 0.459).toFixed(0), "kg CO\u2082"] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC6D4 \uC6A9\uC218 \uC0AC\uC6A9" }), _jsxs("p", { className: "kpi-value", children: [costs.water_m3_month.toLocaleString(), "m\u00B3"] }), _jsxs("p", { className: "kpi-sub", children: [(costs.water_m3_month * 1000).toLocaleString(), "L"] })] })] })] }), _jsxs("div", { className: "card", children: [_jsx("h2", { className: "section-title mb16", children: "\uD56D\uBAA9\uBCC4 \uBE44\uC6A9 \uBE44\uC728" }), _jsx("div", { className: "cost-bars", children: costs.items
                                            .slice()
                                            .sort((a, b) => b.amount_krw - a.amount_krw)
                                            .map(item => (_jsxs("div", { className: "cost-bar-row", children: [_jsxs("div", { className: "cost-bar-meta", children: [_jsx("span", { className: "cost-icon", children: COST_ICONS[item.category] ?? "•" }), _jsx("span", { className: "cost-label-ko", children: item.label_ko }), _jsx("span", { className: "cost-unit-label", children: item.unit_label })] }), _jsx("div", { className: "cost-bar-track", children: _jsx("div", { className: "cost-bar-fill", style: {
                                                            width: `${Math.round(item.pct_of_total * 100)}%`,
                                                            background: COST_BAR_COLOR[item.category] ?? colors.chartwellBlue,
                                                        } }) }), _jsxs("div", { className: "cost-bar-right", children: [_jsxs("span", { className: "cost-amount", children: [Math.round(item.amount_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] }), _jsxs("span", { className: "cost-pct", children: [Math.round(item.pct_of_total * 100), "%"] })] })] }, item.category))) })] }), _jsxs("div", { className: "card", children: [_jsx("h2", { className: "section-title mb16", children: "\uC808\uAC10 \uC778\uC0AC\uC774\uD2B8" }), _jsxs("div", { className: "col-gap8", children: [_jsx(CostInsightRow, { icon: "\u26A1", title: "\uC804\uAE30 \uC808\uAC10", desc: `LED 보광 타이머 최적화로 일 ${(costs.electricity_kwh_month / 30 * 0.1).toFixed(0)}kWh 절약 가능 → 월 약 ${Math.round(costs.electricity_kwh_month / 30 * 0.1 * 30 * 105 / 10000)}만원`, color: COST_BAR_COLOR.electricity }), _jsx(CostInsightRow, { icon: "\uD83D\uDCA7", title: "\uC6A9\uC218 \uC808\uAC10", desc: `점적관개 + EC 정밀제어로 용수 15% 절약 → 월 약 ${Math.round(costs.water_m3_month * 0.15 * 700 / 10000)}만원`, color: COST_BAR_COLOR.water }), _jsx(CostInsightRow, { icon: "\uD83D\uDD25", title: "\uB09C\uBC29 \uC808\uAC10", desc: `보온커튼 야간 운영으로 난방 20% 절약 → 월 약 ${Math.round(costs.items.find(i => i.category === "heating").amount_krw * 0.2 / 10000)}만원`, color: COST_BAR_COLOR.heating })] })] })] })) : _jsx("p", { className: "muted-sm", children: "\uBE44\uC6A9 \uB370\uC774\uD130\uB97C \uBD88\uB7EC\uC624\uB294 \uC911..." })] }));
            // ── AI 상담 ──────────────────────────────────────────────────────────
            case "chat": return (_jsx(AiChat, { farmId: farmId, cropName: meta?.crop, farmName: meta?.name }));
            default: return null;
        }
    }
    // ── Render ────────────────────────────────────────────────────────────────
    return (_jsxs("div", { className: "app-shell", children: [_jsxs("header", { className: "topbar", children: [_jsxs("div", { className: "topbar-brand", children: [_jsxs("div", { className: "topbar-name-row", children: [_jsx("span", { className: "topbar-name", children: meta?.name ?? farmId }), isNoIot && _jsx("span", { className: "badge badge-warn", children: "IoT \uBBF8\uAD6C\uCD95" }), _jsx("button", { className: "gear-btn", onClick: () => setShowFarmSettings(s => !s), title: "\uB18D\uC7A5 \uC124\uC815", children: _jsx(GearIcon, {}) })] }), meta?.crop && _jsx("span", { className: "topbar-crop", children: meta.crop })] }), _jsx("nav", { className: "topbar-tabs", children: TABS.map(({ key, label }) => (_jsx("button", { onClick: () => setTab(key), className: `topbar-tab ${tab === key ? "topbar-tab--active" : ""}`, children: label }, key))) }), _jsxs("div", { className: "pills-row", children: [alertCount > 0 && (_jsxs("button", { onClick: () => setAlertPanelOpen(o => !o), className: `pill pill-danger ${alertPanelOpen ? "pill--active" : ""}`, children: [_jsx(WarnIconSmall, {}), " \uC54C\uB9BC ", alertCount] })), summary?.harvest_days_remaining != null && (_jsxs("span", { className: "pill pill-blue", children: ["\uC218\uD655 D-", summary.harvest_days_remaining] })), summary && (_jsxs("span", { className: "pill pill-green", children: [Math.round(summary.revenue_mtd_krw / 10000), "\uB9CC\uC6D0"] }))] })] }), alertPanelOpen && alerts.length > 0 && (_jsxs("div", { className: "alert-panel", children: [_jsxs("div", { className: "alert-panel-header", children: [_jsxs("span", { className: "alert-panel-title", children: ["\uD604\uC7AC \uC54C\uB9BC ", alertCount, "\uAC74"] }), _jsx("button", { className: "close-btn", onClick: () => setAlertPanelOpen(false), children: "\uB2EB\uAE30 \u2715" })] }), alerts.map(alert => {
                        const c = SEVERITY_COLORS[alert.severity] ?? SEVERITY_COLORS.info;
                        return (_jsxs("div", { className: "alert-item", style: { background: c.bg, borderColor: c.border }, children: [_jsx(AlertIcon, { severity: alert.severity, color: c.text }), _jsxs("div", { children: [_jsxs("div", { className: "alert-item-meta", children: [_jsx("span", { style: { color: c.text, fontSize: "0.65rem", fontWeight: 700, textTransform: "uppercase" }, children: SEVERITY_LABEL[alert.severity] }), _jsxs("span", { className: "muted-xs", children: ["\uD604\uC7AC ", alert.value, alert.unit, " / \uAE30\uC900 ", alert.threshold, alert.unit] })] }), _jsx("p", { className: "alert-msg", children: alert.message_ko })] })] }, alert.id));
                    })] })), _jsxs("div", { className: "app-body", children: [_jsxs("aside", { className: "sidebar", children: [_jsxs("div", { className: "sidebar-farm", children: [_jsxs("div", { className: "sidebar-farm-name-row", children: [_jsx("span", { className: "sidebar-farm-name", children: meta?.name ?? farmId }), _jsx("button", { className: "gear-btn", onClick: () => setShowFarmSettings(s => !s), title: "\uB18D\uC7A5 \uC124\uC815", children: _jsx(GearIcon, {}) })] }), meta?.crop && _jsx("div", { className: "sidebar-crop", children: meta.crop }), meta?.area_m2 && _jsxs("div", { className: "sidebar-area", children: [meta.area_m2.toLocaleString(), "m\u00B2"] })] }), _jsx("nav", { className: "sidebar-nav", children: TABS.map(({ key, label }) => (_jsxs("button", { onClick: () => setTab(key), className: `sidebar-item ${tab === key ? "sidebar-item--active" : ""}`, children: [_jsx(TabIcon, { name: key, active: tab === key }), _jsx("span", { children: label })] }, key))) }), summary && (_jsxs("div", { className: "sidebar-stats", children: [alertCount > 0 && (_jsxs("button", { onClick: () => setAlertPanelOpen(o => !o), className: "sidebar-stat sidebar-stat--danger", children: [_jsx("span", { children: "\uC54C\uB9BC" }), _jsxs("span", { children: [alertCount, "\uAC74"] })] })), summary.harvest_days_remaining != null && (_jsxs("div", { className: "sidebar-stat", children: [_jsx("span", { children: "\uC218\uD655" }), _jsxs("span", { children: ["D-", summary.harvest_days_remaining] })] })), _jsxs("div", { className: "sidebar-stat sidebar-stat--green", children: [_jsx("span", { children: "\uC774\uBC88\uB2EC \uC218\uC775" }), _jsxs("span", { children: [Math.round(summary.revenue_mtd_krw / 10000), "\uB9CC\uC6D0"] })] })] }))] }), _jsxs("main", { className: "main-content", children: [showFarmSettings && (_jsx("div", { style: { marginBottom: "16px" }, children: _jsx(FarmSettings, { farmId: farmId, currentMeta: meta, onSaved: updated => { setMeta(prev => prev ? { ...prev, ...updated } : null); setShowFarmSettings(false); refreshData(); }, onCancel: () => setShowFarmSettings(false) }) })), renderContent()] })] }), _jsx("nav", { className: "bottom-nav", children: TABS.map(({ key, label }) => (_jsxs("button", { onClick: () => setTab(key), className: `bottom-nav-item ${tab === key ? "bottom-nav-item--active" : ""}`, children: [_jsx(TabIcon, { name: key, active: tab === key }), _jsx("span", { children: label })] }, key))) }), _jsx("style", { children: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        /* ── Shell ── */
        .app-shell {
          min-height: 100vh;
          background: ${colors.canvasFog};
          font-family: 'Inter', sans-serif;
          -webkit-font-smoothing: antialiased;
          display: flex; flex-direction: column;
        }

        /* ── Top bar ── */
        .topbar {
          height: 56px; background: ${colors.cloudWhite};
          border-bottom: 1px solid ${colors.stoneBorder};
          display: flex; align-items: center;
          padding: 0 16px; gap: 12px;
          position: sticky; top: 0; z-index: 50;
        }
        .topbar-brand { flex-shrink: 0; }
        .topbar-name-row { display: flex; align-items: center; gap: 8px; }
        .topbar-name  { font-weight: 800; font-size: 0.9375rem; color: ${colors.inkPrimary}; }
        .topbar-crop  { font-size: 0.7rem; color: ${colors.inkMuted}; margin-top: 1px; display: block; }

        /* topbar tabs — tablet only (640–1023px) */
        .topbar-tabs { display: none; flex: 1; overflow-x: auto; gap: 0; }
        .topbar-tabs::-webkit-scrollbar { display: none; }
        .topbar-tab {
          background: none; border: none;
          border-bottom: 2px solid transparent;
          color: ${colors.inkSecondary}; font-weight: 500;
          font-size: 0.875rem; padding: 14px 14px 12px;
          cursor: pointer; white-space: nowrap;
          transition: color 150ms;
        }
        .topbar-tab--active {
          border-bottom-color: ${colors.chartwellBlue};
          color: ${colors.chartwellBlue}; font-weight: 700;
        }

        /* pills */
        .pills-row { display: flex; gap: 6px; align-items: center; margin-left: auto; flex-shrink: 0; }
        .pill {
          border-radius: ${radius.badge}; padding: 4px 10px;
          font-size: 0.72rem; font-weight: 700; border: 1.5px solid transparent;
          white-space: nowrap;
        }
        .pill-danger { background: ${colors.dangerBg}; color: ${colors.dangerRed}; border-color: ${colors.dangerRed}; cursor: pointer; display: flex; align-items: center; gap: 4px; transition: background 150ms, color 150ms; }
        .pill-danger.pill--active { background: ${colors.dangerRed}; color: #fff; }
        .pill-blue   { background: ${colors.chartwellBlueBg}; color: ${colors.chartwellBlue}; }
        .pill-green  { background: ${colors.successBg}; color: ${colors.successGreen}; }

        /* ── Alert panel ── */
        .alert-panel {
          background: ${colors.cloudWhite};
          border-bottom: 1px solid ${colors.stoneBorder};
          padding: 12px 16px; display: flex; flex-direction: column; gap: 8px;
          position: sticky; top: 56px; z-index: 49;
          box-shadow: 0 4px 12px rgba(0,0,0,0.06);
        }
        .alert-panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
        .alert-panel-title  { font-size: 0.8125rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .close-btn { background: none; border: none; cursor: pointer; color: ${colors.inkMuted}; font-size: 0.75rem; padding: 2px 6px; }
        .alert-item {
          border: 1px solid; border-radius: 8px; padding: 10px 14px;
          display: flex; align-items: flex-start; gap: 10px;
        }
        .alert-item-meta { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
        .alert-msg { font-size: 0.875rem; color: ${colors.inkPrimary}; line-height: 1.4; }

        /* ── Body layout ── */
        .app-body { display: flex; flex: 1; min-height: 0; }

        /* ── Sidebar (desktop ≥1024px) ── */
        .sidebar { display: none; }

        /* ── Main content ── */
        .main-content { flex: 1; padding: 16px; overflow-y: auto; padding-bottom: 80px; }

        /* ── Bottom nav (mobile <640px) ── */
        .bottom-nav {
          position: fixed; bottom: 0; left: 0; right: 0;
          background: ${colors.cloudWhite};
          border-top: 1px solid ${colors.stoneBorder};
          display: flex; z-index: 50;
        }
        .bottom-nav-item {
          flex: 1; background: none; border: none;
          padding: 10px 4px 8px;
          display: flex; flex-direction: column; align-items: center; gap: 3px;
          cursor: pointer; color: ${colors.inkMuted};
          font-size: 0.65rem; font-weight: 500; min-height: 52px;
          transition: color 150ms;
        }
        .bottom-nav-item--active { color: ${colors.chartwellBlue}; font-weight: 700; }

        /* ── Tablet: 640–1023px ── */
        @media (min-width: 640px) {
          .bottom-nav  { display: none !important; }
          .topbar-tabs { display: flex; }
          .main-content { padding-bottom: 16px; }
        }

        /* 톱니바퀴 버튼 (topbar·sidebar 공용) */
        .gear-btn {
          background: none; border: none;
          padding: 3px 4px; margin-left: 4px;
          cursor: pointer; border-radius: 6px;
          color: ${colors.inkMuted};
          display: inline-flex; align-items: center;
          transition: color 150ms, background 150ms;
          flex-shrink: 0;
        }
        .gear-btn:hover { color: ${colors.chartwellBlue}; background: ${colors.chartwellBlueBg}; }

        /* 사이드바 농장명 행 */
        .sidebar-farm-name-row {
          display: flex; align-items: center; gap: 2px;
        }

        /* ── Desktop: ≥1024px ── */
        @media (min-width: 1024px) {
          .topbar-brand { display: none; }
          .topbar-tabs { display: none; }

          .sidebar {
            display: flex; flex-direction: column;
            width: 220px; min-width: 220px;
            background: ${colors.cloudWhite};
            border-right: 1px solid ${colors.stoneBorder};
            position: sticky; top: 56px;
            height: calc(100vh - 56px);
            overflow-y: auto; flex-shrink: 0;
          }
          .sidebar-farm {
            padding: 20px 16px 12px;
            border-bottom: 1px solid ${colors.stoneBorder};
          }
          .sidebar-farm-name { font-weight: 800; font-size: 0.9375rem; color: ${colors.inkPrimary}; }
          .sidebar-crop { font-size: 0.8rem; color: ${colors.inkMuted}; margin-top: 2px; }
          .sidebar-area { font-size: 0.75rem; color: ${colors.inkMuted}; margin-top: 2px; }
          .sidebar-nav  { padding: 8px 0; flex: 1; }
          .sidebar-item {
            width: 100%; background: none; border: none;
            display: flex; align-items: center; gap: 10px;
            padding: 11px 16px; cursor: pointer;
            font-size: 0.9375rem; font-weight: 500;
            color: ${colors.inkSecondary}; text-align: left;
            border-radius: 0; transition: background 120ms, color 120ms;
          }
          .sidebar-item:hover { background: ${colors.canvasFog}; color: ${colors.inkPrimary}; }
          .sidebar-item--active {
            background: ${colors.chartwellBlueBg} !important;
            color: ${colors.chartwellBlue} !important; font-weight: 700;
            border-right: 3px solid ${colors.chartwellBlue};
          }
          .sidebar-stats {
            padding: 12px;
            border-top: 1px solid ${colors.stoneBorder};
            display: flex; flex-direction: column; gap: 6px;
          }
          .sidebar-stat {
            display: flex; justify-content: space-between; align-items: center;
            padding: 8px 10px; border-radius: 8px;
            background: ${colors.canvasFog};
            font-size: 0.8125rem; font-weight: 600; color: ${colors.inkSecondary};
            border: none; cursor: default; width: 100%;
          }
          .sidebar-stat--danger { background: ${colors.dangerBg}; color: ${colors.dangerRed}; cursor: pointer; }
          .sidebar-stat--green  { background: ${colors.successBg}; color: ${colors.successGreen}; }

          .main-content { padding: 24px 28px; max-width: 900px; padding-bottom: 24px; }
        }

        /* ── Reusable ── */
        .card {
          background: ${colors.cloudWhite}; border-radius: ${radius.card};
          box-shadow: ${shadow.card}; border: 1px solid ${colors.stoneBorder};
          padding: 24px;
        }
        .col-gap  { display: flex; flex-direction: column; gap: 12px; }
        .col-gap8 { display: flex; flex-direction: column; gap: 8px; }
        .row-gap8 { display: flex; align-items: baseline; gap: 8px; }
        .row-between { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .mb16 { margin-bottom: 16px; }
        .loading-center { text-align: center; padding: 48px 0; color: ${colors.inkMuted}; font-size: 1rem; }

        .section-title { font-size: 1rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
        .kpi-cell { padding: 14px 16px; background: ${colors.canvasFog}; border-radius: 8px; }
        .kpi-label { font-size: 0.8125rem; color: ${colors.inkSecondary}; margin-bottom: 4px; }
        .kpi-value { font-size: 1.25rem; font-weight: 800; color: ${colors.inkPrimary}; }
        .kpi-sub   { font-size: 0.7rem; color: ${colors.inkMuted}; margin-top: 2px; }

        .rank-label { font-size: 0.75rem; font-weight: 600; color: ${colors.inkMuted}; margin-right: 8px; }
        .body-md    { font-size: 1rem; font-weight: 600; color: ${colors.inkPrimary}; }
        .profit-num { font-size: 1rem; font-weight: 800; white-space: nowrap; }
        .muted-sm   { font-size: 0.8rem; color: ${colors.inkMuted}; }
        .muted-xs   { font-size: 0.7rem; color: ${colors.inkMuted}; }
        .inline-link {
          background: none; border: none; padding: 0;
          color: ${colors.chartwellBlue}; font-weight: 700;
          font-size: inherit; cursor: pointer; text-decoration: underline;
        }

        .badge { border-radius: ${radius.badge}; padding: 2px 7px; font-size: 0.65rem; font-weight: 700; }
        .badge-warn { background: ${colors.warningBg}; color: ${colors.warningAmber}; }

        /* ── Warning card ── */
        .warn-card {
          background: ${colors.warningBg}; border: 1.5px solid ${colors.warningAmber};
          border-radius: ${radius.card}; padding: 20px 24px;
          display: flex; align-items: flex-start; gap: 12px;
        }
        .warn-title { font-weight: 700; color: ${colors.inkPrimary}; font-size: 1rem; }
        .warn-body  { color: ${colors.inkSecondary}; font-size: 0.9rem; margin-top: 4px; line-height: 1.6; }

        /* ── Cost bars ── */
        .cost-bars { display: flex; flex-direction: column; gap: 14px; }
        .cost-bar-row {}
        .cost-bar-meta {
          display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
        }
        .cost-icon       { font-size: 0.9rem; flex-shrink: 0; }
        .cost-label-ko   { font-size: 0.875rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .cost-unit-label { font-size: 0.7rem; color: ${colors.inkMuted}; margin-left: auto; text-align: right; }
        .cost-bar-track  { height: 8px; background: ${colors.canvasFog}; border-radius: 4px; overflow: hidden; margin-bottom: 4px; }
        .cost-bar-fill   { height: 100%; border-radius: 4px; transition: width 400ms ease; }
        .cost-bar-right  { display: flex; justify-content: space-between; }
        .cost-amount     { font-size: 0.875rem; font-weight: 700; color: ${colors.inkPrimary}; }
        .cost-pct        { font-size: 0.75rem; color: ${colors.inkMuted}; }

        /* ── Cost insight ── */
        .cost-insight {
          display: flex; align-items: flex-start; gap: 12px;
          padding: 12px 14px; border-radius: 8px;
          background: ${colors.canvasFog};
        }
        .cost-insight-icon { font-size: 1.1rem; flex-shrink: 0; margin-top: 1px; }
        .cost-insight-title { font-size: 0.875rem; font-weight: 700; color: ${colors.inkPrimary}; margin-bottom: 2px; }
        .cost-insight-desc  { font-size: 0.8125rem; color: ${colors.inkSecondary}; line-height: 1.5; }

        /* ── Focus & a11y ── */
        button:focus-visible { outline: 3px solid ${colors.chartwellBlueBg}; outline-offset: 2px; }
        input:focus { outline: none; border-color: ${colors.chartwellBlue} !important; box-shadow: 0 0 0 3px ${colors.chartwellBlueBg}; }
        input[type=number]::-webkit-inner-spin-button,
        input[type=number]::-webkit-outer-spin-button { opacity: 1; }
        @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
      ` })] }));
}
const WHATIF_FIELDS = [
    { key: "temp_internal", label: "내부 온도", unit: "°C", min: 5, max: 40, step: 0.5 },
    { key: "humidity_int", label: "내부 습도", unit: "%", min: 30, max: 95, step: 1 },
    { key: "co2_ppm", label: "CO₂ 농도", unit: "ppm", min: 400, max: 1800, step: 50 },
    { key: "solar_rad", label: "일사량", unit: "W/m²", min: 0, max: 800, step: 10 },
    { key: "ec_dsm", label: "EC (양액)", unit: "dS/m", min: 0.5, max: 4.5, step: 0.1 },
];
function WhatIfPanel({ farmId, currentEnv }) {
    // 슬라이더 초기값 = 현재 환경값 (없으면 중앙값)
    const initVals = () => {
        const v = {};
        WHATIF_FIELDS.forEach(f => {
            v[f.key] = currentEnv[f.key] ?? (f.min + f.max) / 2;
        });
        return v;
    };
    const [vals, setVals] = useState(initVals);
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const timerRef = useRef(null);
    // 현재 환경값 변경 시 슬라이더 리셋
    useEffect(() => { setVals(initVals()); }, [farmId]); // eslint-disable-line
    function handleSlider(key, val) {
        const next = { ...vals, [key]: val };
        setVals(next);
        // 300ms 디바운스
        if (timerRef.current)
            clearTimeout(timerRef.current);
        timerRef.current = setTimeout(async () => {
            setLoading(true);
            try {
                const res = await fetch(`/api/farms/${farmId}/whatif`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(next),
                });
                if (res.ok)
                    setResult(await res.json());
            }
            catch { /* ignore */ }
            finally {
                setLoading(false);
            }
        }, 300);
    }
    function handleReset() {
        const reset = initVals();
        setVals(reset);
        setResult(null);
    }
    const deltaColor = !result ? colors.inkMuted
        : result.delta_krw > 0 ? colors.successGreen
            : result.delta_krw < 0 ? colors.dangerRed
                : colors.inkMuted;
    const deltaSign = result && result.delta_krw > 0 ? "+" : "";
    return (_jsxs("div", { className: "card", children: [_jsxs("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }, children: [_jsxs("div", { children: [_jsx("h2", { className: "section-title", children: "What-if \uC2DC\uBBAC\uB808\uC774\uD130" }), _jsx("p", { className: "muted-sm", style: { marginTop: 3 }, children: "\uC2AC\uB77C\uC774\uB354\uB97C \uC870\uC808\uD558\uBA74 ML \uBAA8\uB378\uC774 \uC218\uC775 \uBCC0\uD654\uB97C \uC608\uCE21\uD569\uB2C8\uB2E4" })] }), _jsx("button", { onClick: handleReset, style: {
                            fontSize: "0.78rem", padding: "5px 12px", borderRadius: "9999px",
                            border: `1.5px solid ${colors.stoneBorder}`, background: "#fff",
                            color: colors.inkMuted, cursor: "pointer", whiteSpace: "nowrap",
                        }, children: "\uD604\uC7AC\uAC12\uC73C\uB85C \uCD08\uAE30\uD654" })] }), _jsx("div", { style: { display: "flex", flexDirection: "column", gap: 18, marginBottom: 20 }, children: WHATIF_FIELDS.map(f => {
                    const cur = currentEnv[f.key];
                    const val = vals[f.key];
                    const changed = cur != null && Math.abs(val - cur) > 0.01;
                    return (_jsxs("div", { children: [_jsxs("div", { style: { display: "flex", justifyContent: "space-between", marginBottom: 6 }, children: [_jsxs("span", { style: { fontSize: "0.82rem", fontWeight: 600, color: colors.inkPrimary }, children: [f.label, changed && cur != null && (_jsxs("span", { style: { fontSize: "0.72rem", color: colors.warningAmber, marginLeft: 8 }, children: ["\uAE30\uC900 ", cur.toFixed(f.step < 1 ? 1 : 0), f.unit] }))] }), _jsxs("span", { style: {
                                            fontSize: "0.9rem", fontWeight: 700,
                                            color: changed ? colors.chartwellBlue : colors.inkPrimary,
                                            minWidth: 72, textAlign: "right",
                                        }, children: [val.toFixed(f.step < 1 ? 1 : 0), " ", f.unit] })] }), _jsxs("div", { style: { position: "relative" }, children: [_jsx("input", { type: "range", min: f.min, max: f.max, step: f.step, value: val, onChange: e => handleSlider(f.key, Number(e.target.value)), style: { width: "100%", accentColor: colors.chartwellBlue, cursor: "pointer" } }), cur != null && (_jsx("div", { style: {
                                            position: "absolute", top: "50%", transform: "translate(-50%, -50%)",
                                            left: `${((cur - f.min) / (f.max - f.min)) * 100}%`,
                                            width: 2, height: 12,
                                            background: colors.inkMuted, opacity: 0.4,
                                            pointerEvents: "none",
                                        } }))] }), _jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: colors.inkMuted, marginTop: 2 }, children: [_jsxs("span", { children: [f.min, f.unit] }), _jsxs("span", { children: [f.max, f.unit] })] })] }, f.key));
                }) }), _jsx("div", { style: {
                    borderRadius: 12, padding: "18px 20px",
                    background: result
                        ? result.delta_krw > 0 ? "#f0fdf4" : result.delta_krw < 0 ? "#fff1f2" : colors.canvasFog
                        : colors.canvasFog,
                    border: `1.5px solid ${result
                        ? result.delta_krw > 0 ? "#86efac" : result.delta_krw < 0 ? "#fca5a5" : colors.stoneBorder
                        : colors.stoneBorder}`,
                    transition: "background 300ms, border-color 300ms",
                }, children: loading ? (_jsx("p", { style: { textAlign: "center", color: colors.inkMuted, fontSize: "0.85rem" }, children: "\uACC4\uC0B0 \uC911\u2026" })) : result ? (_jsxs("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }, children: [_jsxs("div", { children: [_jsx("p", { style: { fontSize: "0.78rem", color: colors.inkMuted, marginBottom: 4 }, children: "\uC608\uC0C1 \uC218\uC775 \uBCC0\uD654" }), _jsxs("p", { style: { fontSize: "2rem", fontWeight: 800, color: deltaColor, lineHeight: 1 }, children: [deltaSign, Math.round(result.delta_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] }), _jsxs("p", { style: { fontSize: "0.78rem", color: deltaColor, marginTop: 4 }, children: [deltaSign, result.delta_pct.toFixed(1), "% \u00B7 ", result.model_used === "ml_model" ? "ML 예측" : "통계 추정"] })] }), _jsxs("div", { style: { textAlign: "right" }, children: [_jsx("p", { style: { fontSize: "0.72rem", color: colors.inkMuted }, children: "\uD604\uC7AC \uC608\uCE21" }), _jsxs("p", { style: { fontSize: "1rem", fontWeight: 700, color: colors.inkPrimary }, children: [Math.round(result.baseline_revenue_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] }), _jsx("p", { style: { fontSize: "0.72rem", color: colors.inkMuted, marginTop: 6 }, children: "\uBCC0\uACBD \uD6C4 \uC608\uCE21" }), _jsxs("p", { style: { fontSize: "1rem", fontWeight: 700, color: deltaColor }, children: [Math.round(result.whatif_revenue_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] })] })] })) : (_jsx("p", { style: { textAlign: "center", color: colors.inkMuted, fontSize: "0.85rem" }, children: "\uC2AC\uB77C\uC774\uB354\uB97C \uC870\uC808\uD558\uBA74 \uC218\uC775 \uBCC0\uD654\uB97C \uC608\uCE21\uD569\uB2C8\uB2E4" })) })] }));
}
// ── 수확 예측 탭 ──────────────────────────────────────────────────────────────
function HarvestTab({ harvest, meta }) {
    if (!harvest) {
        return (_jsx("div", { className: "card", style: { textAlign: "center", padding: "40px", color: colors.inkMuted }, children: "\uC218\uD655 \uC608\uCE21 \uB370\uC774\uD130\uB97C \uBD88\uB7EC\uC624\uB294 \uC911\uC785\uB2C8\uB2E4\u2026" }));
    }
    // D-day 계산
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const harvestDt = new Date(harvest.predicted_date);
    const dDay = Math.round((harvestDt.getTime() - today.getTime()) / 86400000);
    // 날짜 표기 (M월 D일)
    const dateLabel = harvestDt.toLocaleDateString("ko-KR", { month: "long", day: "numeric" });
    // 총 출하 예상량 (면적 × 수확량/m²)
    const totalKg = meta?.area_m2 != null
        ? (harvest.predicted_yield_kg_m2 * meta.area_m2).toFixed(0)
        : null;
    const confPct = Math.round(harvest.confidence * 100);
    // 신뢰도 색상
    const confColor = confPct >= 75 ? colors.successGreen
        : confPct >= 55 ? colors.warningAmber
            : colors.dangerRed;
    return (_jsxs("div", { className: "col-gap", children: [_jsxs("div", { className: "card", children: [_jsxs("div", { className: "row-gap8 mb16", children: [_jsx("h2", { className: "section-title", children: "\uC218\uD655 \uC608\uCE21" }), meta?.crop && _jsxs("span", { className: "muted-sm", children: ["\u2014 ", meta.crop] })] }), _jsxs("div", { className: "kpi-grid", children: [_jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC608\uC0C1 \uC218\uD655\uC77C" }), _jsx("p", { className: "kpi-value", children: dateLabel }), _jsxs("p", { className: "kpi-sub", style: { color: dDay <= 7 ? colors.dangerRed : colors.inkMuted }, children: ["D-", dDay] })] }), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC608\uC0C1 \uC218\uD655\uB7C9" }), _jsxs("p", { className: "kpi-value", children: [harvest.predicted_yield_kg_m2.toFixed(2), " kg/m\u00B2"] }), _jsxs("p", { className: "kpi-sub", children: ["\uC2E0\uB8B0\uB3C4 ", confPct, "%"] })] }), totalKg != null && (_jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uCD1D \uCD9C\uD558 \uC608\uC0C1\uB7C9" }), _jsxs("p", { className: "kpi-value", children: [Number(totalKg).toLocaleString(), " kg"] }), _jsxs("p", { className: "kpi-sub", children: [meta?.area_m2?.toLocaleString(), "m\u00B2 \uAE30\uC900"] })] })), _jsxs("div", { className: "kpi-cell", children: [_jsx("p", { className: "kpi-label", children: "\uC608\uCE21 \uC2E0\uB8B0\uB3C4" }), _jsxs("p", { className: "kpi-value", style: { color: confColor }, children: [confPct, "%"] }), _jsx("p", { className: "kpi-sub", children: "GDD \uAE30\uBC18 \uCD94\uC815" })] })] })] }), _jsxs("div", { className: "card", children: [_jsx("h2", { className: "section-title mb16", children: "\uC218\uD655\uAE4C\uC9C0 \uB0A8\uC740 \uC77C\uC218" }), _jsxs("div", { style: { display: "flex", alignItems: "center", gap: "14px" }, children: [_jsxs("span", { style: { fontSize: "2.5rem", fontWeight: 800, color: dDay <= 7 ? colors.dangerRed : colors.chartwellBlue, minWidth: 64 }, children: ["D-", dDay] }), _jsxs("div", { style: { flex: 1 }, children: [_jsx("div", { style: { height: 10, background: colors.canvasFog, borderRadius: 5, overflow: "hidden" }, children: _jsx("div", { style: {
                                                height: "100%", borderRadius: 5,
                                                width: `${Math.max(4, Math.min(100, Math.round((1 - dDay / 60) * 100)))}%`,
                                                background: dDay <= 7 ? colors.dangerRed : colors.chartwellBlue,
                                                transition: "width 600ms ease",
                                            } }) }), _jsxs("div", { style: { display: "flex", justifyContent: "space-between", marginTop: 6 }, children: [_jsx("span", { className: "muted-xs", children: "\uC624\uB298" }), _jsxs("span", { className: "muted-xs", children: ["\uC218\uD655 \uC608\uC815 ", dateLabel] })] })] })] })] }), _jsxs("div", { style: {
                    background: colors.chartwellBlueBg, borderRadius: 10,
                    padding: "14px 18px", fontSize: "0.82rem",
                    color: colors.chartwellBlue, lineHeight: 1.6,
                }, children: ["\uD83D\uDCA1 \uB0B4\uBD80 \uC628\uB3C4\uB97C 1\u00B0C \uB192\uC774\uBA74 \uC218\uD655\uC77C\uC774 \uC57D 1~2\uC77C \uC55E\uB2F9\uACA8\uC9C8 \uC218 \uC788\uC2B5\uB2C8\uB2E4. \uC815\uBC00 \uC608\uCE21\uC740 ", _jsx("strong", { children: "AI \uCD94\uCC9C" }), " \uD0ED\uC5D0\uC11C \uD655\uC778\uD558\uC138\uC694."] })] }));
}
// ── 비용 바 색상 ──────────────────────────────────────────────────────────────
const COST_BAR_COLOR = {
    electricity: "#f59e0b", // amber
    water: "#3ba6f1", // blue
    heating: "#ef4444", // red
    labor: "#8b5cf6", // purple
    nutrients: "#16a34a", // green
    pesticides: "#6b7280", // gray
};
// ── 절감 인사이트 행 ──────────────────────────────────────────────────────────
function CostInsightRow({ icon, title, desc, color }) {
    return (_jsxs("div", { className: "cost-insight", style: { borderLeft: `3px solid ${color}` }, children: [_jsx("span", { className: "cost-insight-icon", children: icon }), _jsxs("div", { children: [_jsx("p", { className: "cost-insight-title", children: title }), _jsx("p", { className: "cost-insight-desc", children: desc })] })] }));
}
// ── Tab icons ─────────────────────────────────────────────────────────────────
function TabIcon({ name, active }) {
    const c = active ? colors.chartwellBlue : colors.inkMuted;
    switch (name) {
        case "recommendations":
            return _jsx("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: c, strokeWidth: "2", children: _jsx("path", { d: "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" }) });
        case "environment":
            return _jsx("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: c, strokeWidth: "2", children: _jsx("path", { d: "M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z" }) });
        case "harvest":
            return _jsxs("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: c, strokeWidth: "2", children: [_jsx("rect", { x: "3", y: "4", width: "18", height: "18", rx: "2", ry: "2" }), _jsx("line", { x1: "16", y1: "2", x2: "16", y2: "6" }), _jsx("line", { x1: "8", y1: "2", x2: "8", y2: "6" }), _jsx("line", { x1: "3", y1: "10", x2: "21", y2: "10" })] });
        case "revenue":
            return _jsxs("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: c, strokeWidth: "2", children: [_jsx("line", { x1: "12", y1: "1", x2: "12", y2: "23" }), _jsx("path", { d: "M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" })] });
        case "costs":
            return _jsx("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: c, strokeWidth: "2", children: _jsx("path", { d: "M22 12h-4l-3 9L9 3l-3 9H2" }) });
        case "chat":
            return _jsxs("svg", { width: "20", height: "20", viewBox: "0 0 24 24", fill: "none", stroke: c, strokeWidth: "2", children: [_jsx("path", { d: "M12 2a9 9 0 0 1 9 9c0 4-2.5 7-6 8.5V22l-3-2-3 2v-2.5C5.5 18 3 15 3 11a9 9 0 0 1 9-9z" }), _jsx("circle", { cx: "9", cy: "11", r: "1", fill: c }), _jsx("circle", { cx: "15", cy: "11", r: "1", fill: c })] });
        default: return null;
    }
}
// ── Inline SVG helpers ────────────────────────────────────────────────────────
function WarnIcon() {
    return _jsxs("svg", { width: "22", height: "22", viewBox: "0 0 24 24", fill: "none", stroke: colors.warningAmber, strokeWidth: "2.5", style: { flexShrink: 0, marginTop: 2 }, children: [_jsx("path", { d: "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" }), _jsx("line", { x1: "12", y1: "9", x2: "12", y2: "13" }), _jsx("line", { x1: "12", y1: "17", x2: "12.01", y2: "17" })] });
}
function WarnIconSmall() {
    return _jsxs("svg", { width: "11", height: "11", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "2.5", children: [_jsx("path", { d: "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" }), _jsx("line", { x1: "12", y1: "9", x2: "12", y2: "13" }), _jsx("line", { x1: "12", y1: "17", x2: "12.01", y2: "17" })] });
}
function AlertIcon({ severity, color }) {
    return _jsx("svg", { width: "16", height: "16", viewBox: "0 0 24 24", fill: "none", stroke: color, strokeWidth: "2.5", style: { flexShrink: 0, marginTop: 1 }, children: severity === "info"
            ? _jsxs(_Fragment, { children: [_jsx("circle", { cx: "12", cy: "12", r: "10" }), _jsx("line", { x1: "12", y1: "8", x2: "12", y2: "12" }), _jsx("line", { x1: "12", y1: "16", x2: "12.01", y2: "16" })] })
            : _jsxs(_Fragment, { children: [_jsx("path", { d: "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" }), _jsx("line", { x1: "12", y1: "9", x2: "12", y2: "13" }), _jsx("line", { x1: "12", y1: "17", x2: "12.01", y2: "17" })] }) });
}
