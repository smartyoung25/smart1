import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState, useEffect } from "react";
import { colors, radius, shadow } from "../design-system/tokens";
// ── Fetch helper ──────────────────────────────────────────────────────────────
async function fetchJson(url) {
    const res = await fetch(url);
    if (!res.ok)
        throw new Error(`${url} → ${res.status}`);
    return res.json();
}
const NAV_ITEMS = [
    { key: "overview", label: "전체 현황" },
    { key: "models", label: "AI 모델" },
    { key: "sources", label: "데이터 소스" },
    { key: "registry", label: "변수 레지스트리" },
    { key: "pipeline", label: "학습 파이프라인" },
];
// R² 신호등 색상
function r2Color(v) {
    if (v === null)
        return colors.inkMuted;
    if (v >= 0.90)
        return colors.successGreen;
    if (v >= 0.70)
        return colors.warningAmber;
    return colors.dangerRed;
}
// 배지 스타일
function badge(ok) {
    return {
        display: "inline-block", padding: "3px 10px", borderRadius: radius.badge,
        fontSize: "0.72rem", fontWeight: 700,
        background: ok ? colors.successBg : colors.dangerBg,
        color: ok ? colors.successGreen : colors.dangerRed,
    };
}
export function AdminDashboard() {
    const [section, setSection] = useState("overview");
    const [overview, setOverview] = useState(null);
    const [cropModels, setCropModels] = useState([]);
    const [sources, setSources] = useState([]);
    const [registry, setRegistry] = useState([]);
    const [runs, setRuns] = useState([]);
    const [triggering, setTriggering] = useState(false);
    const [triggered, setTriggered] = useState(false);
    const [err, setErr] = useState(null);
    useEffect(() => {
        Promise.all([
            fetchJson("/api/admin/overview"),
            fetchJson("/api/admin/models/crops"),
            fetchJson("/api/admin/data-sources"),
            fetchJson("/api/admin/variable-registry"),
            fetchJson("/api/admin/pipeline/runs"),
        ]).then(([ov, cm, sr, vr, pr]) => {
            setOverview(ov);
            setCropModels(cm.crops);
            setSources(sr.sources);
            setRegistry(vr.variables);
            setRuns(pr.runs);
        }).catch(e => setErr(String(e)));
    }, []);
    async function handleTrigger() {
        setTriggering(true);
        try {
            await fetch("/api/admin/pipeline/trigger", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reason: "manual" }),
            });
            setTriggered(true);
        }
        finally {
            setTriggering(false);
        }
    }
    // ── Shared styles ────────────────────────────────────────────────────────────
    const card = {
        background: colors.cloudWhite, borderRadius: radius.card,
        boxShadow: shadow.card, border: `1px solid ${colors.stoneBorder}`,
    };
    const th = {
        padding: "12px 16px", textAlign: "left",
        fontSize: "0.72rem", fontWeight: 700,
        color: colors.inkSecondary, letterSpacing: "0.04em", textTransform: "uppercase",
    };
    const td = { padding: "13px 16px", fontSize: "0.875rem" };
    // ── Render ───────────────────────────────────────────────────────────────────
    return (_jsxs("div", { style: { display: "flex", minHeight: "100vh", fontFamily: "'Inter', sans-serif", background: colors.canvasFog, WebkitFontSmoothing: "antialiased" }, children: [_jsxs("aside", { style: {
                    width: 220, flexShrink: 0, background: colors.cloudWhite,
                    borderRight: `1px solid ${colors.stoneBorder}`,
                    display: "flex", flexDirection: "column",
                    position: "sticky", top: 0, height: "100vh",
                }, children: [_jsxs("div", { style: { padding: "20px 16px 16px", borderBottom: `1px solid ${colors.stoneBorder}` }, children: [_jsx("p", { style: { fontSize: "0.7rem", fontWeight: 600, color: colors.inkMuted, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }, children: "\uD50C\uB7AB\uD3FC \uAD00\uB9AC" }), _jsx("p", { style: { fontSize: "1rem", fontWeight: 800, color: colors.inkPrimary }, children: "Smart Farm" })] }), _jsx("nav", { style: { padding: 8 }, children: NAV_ITEMS.map(({ key, label }) => (_jsx("button", { onClick: () => setSection(key), style: {
                                display: "block", width: "100%", textAlign: "left",
                                padding: "10px 12px", marginBottom: 2,
                                borderRadius: 8, border: "none",
                                background: section === key ? colors.chartwellBlueBg : "none",
                                color: section === key ? colors.chartwellBlue : colors.inkSecondary,
                                fontWeight: section === key ? 700 : 500,
                                fontSize: "0.9375rem", cursor: "pointer",
                                transition: "background 150ms, color 150ms",
                            }, children: label }, key))) }), overview && (_jsxs("div", { style: { marginTop: "auto", padding: "12px", borderTop: `1px solid ${colors.stoneBorder}` }, children: [_jsx("div", { style: { fontSize: "0.72rem", color: colors.inkMuted, marginBottom: 6 }, children: "\uC5F0\uACB0 \uD604\uD669" }), _jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 4 }, children: [_jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }, children: [_jsx("span", { style: { color: colors.inkSecondary }, children: "\uC804\uCCB4 \uB18D\uAC00" }), _jsxs("span", { style: { fontWeight: 700, color: colors.inkPrimary }, children: [overview.connected_farms, "\uAC1C"] })] }), _jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }, children: [_jsx("span", { style: { color: colors.inkSecondary }, children: "IoT \uAD6C\uCD95" }), _jsxs("span", { style: { fontWeight: 700, color: colors.successGreen }, children: [overview.iot_farms, "\uAC1C"] })] }), _jsxs("div", { style: { display: "flex", justifyContent: "space-between", fontSize: "0.8rem" }, children: [_jsx("span", { style: { color: colors.inkSecondary }, children: "\uBAA8\uB378 \uB85C\uB4DC" }), _jsxs("span", { style: { fontWeight: 700, color: colors.chartwellBlue }, children: [overview.models_loaded, "\uAC1C"] })] })] })] }))] }), _jsxs("main", { style: { flex: 1, padding: 24, overflow: "auto" }, children: [_jsx("h1", { style: { fontSize: "1.25rem", fontWeight: 800, color: colors.inkPrimary, marginBottom: 20 }, children: NAV_ITEMS.find(n => n.key === section)?.label }), err && (_jsxs("div", { style: { background: colors.dangerBg, border: `1px solid ${colors.dangerRed}`, borderRadius: 8, padding: "12px 16px", marginBottom: 16, color: colors.dangerRed, fontSize: "0.85rem" }, children: ["API \uC624\uB958: ", err] })), section === "overview" && (_jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 20 }, children: [_jsx("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 16 }, children: overview ? [
                                    { label: "연결 농가", value: `${overview.connected_farms}개`, color: colors.chartwellBlue },
                                    { label: "IoT 구축", value: `${overview.iot_farms}개`, color: colors.successGreen },
                                    { label: "평균 훈련 R²", value: overview.avg_model_r2.toFixed(3), color: r2Color(overview.avg_model_r2) },
                                    { label: "로드된 모델", value: `${overview.models_loaded}개`, color: colors.chartwellBlue },
                                    { label: "데이터 완전성", value: `${overview.data_completeness_pct}%`, color: colors.warningAmber },
                                    { label: "소득 향상률", value: `+${overview.income_improvement_pct.toFixed(1)}%`, color: colors.successGreen },
                                ].map(({ label, value, color }) => (_jsxs("div", { style: { ...card, padding: 20 }, children: [_jsx("p", { style: { fontSize: "0.82rem", color: colors.inkSecondary, marginBottom: 8 }, children: label }), _jsx("p", { style: { fontSize: "1.75rem", fontWeight: 800, color }, children: value })] }, label))) : (_jsx("div", { style: { gridColumn: "1/-1", textAlign: "center", padding: 40, color: colors.inkMuted }, children: "\uBD88\uB7EC\uC624\uB294 \uC911\u2026" })) }), cropModels.length > 0 && (_jsxs("div", { style: { ...card, overflow: "hidden" }, children: [_jsx("div", { style: { padding: "16px 20px", borderBottom: `1px solid ${colors.stoneBorder}` }, children: _jsx("span", { style: { fontWeight: 700, color: colors.inkPrimary }, children: "\uC791\uBAA9\uBCC4 \uBAA8\uB378 \uC694\uC57D" }) }), _jsxs("table", { style: { width: "100%", borderCollapse: "collapse" }, children: [_jsx("thead", { children: _jsx("tr", { style: { background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }, children: ["작목", "상태", "훈련 R²", "훈련 MAPE", "학습 데이터"].map(h => (_jsx("th", { style: th, children: h }, h))) }) }), _jsx("tbody", { children: cropModels.map((m, i) => (_jsxs("tr", { style: { borderBottom: i < cropModels.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }, children: [_jsx("td", { style: { ...td, fontWeight: 700, color: colors.inkPrimary }, children: m.crop_ko }), _jsx("td", { style: td, children: _jsx("span", { style: badge(m.status === "loaded"), children: m.status === "loaded" ? "로드됨" : "없음" }) }), _jsx("td", { style: { ...td, fontWeight: 700, color: r2Color(m.train_r2) }, children: m.train_r2 != null ? m.train_r2.toFixed(3) : "—" }), _jsx("td", { style: { ...td, color: colors.inkSecondary }, children: m.train_mape != null ? `${m.train_mape.toFixed(1)}%` : "—" }), _jsx("td", { style: { ...td, color: colors.inkMuted }, children: m.n_train != null ? `${m.n_train.toLocaleString()}행` : "—" })] }, m.crop_ko))) })] })] }))] })), section === "models" && (_jsx("div", { style: { display: "flex", flexDirection: "column", gap: 16 }, children: cropModels.length === 0
                            ? _jsx("div", { style: { textAlign: "center", padding: 40, color: colors.inkMuted }, children: "\uBD88\uB7EC\uC624\uB294 \uC911\u2026" })
                            : cropModels.map(m => (_jsxs("div", { style: { ...card, overflow: "hidden" }, children: [_jsxs("div", { style: {
                                            padding: "14px 20px", borderBottom: `1px solid ${colors.stoneBorder}`,
                                            display: "flex", alignItems: "center", justifyContent: "space-between",
                                        }, children: [_jsxs("div", { style: { display: "flex", alignItems: "center", gap: 12 }, children: [_jsx("span", { style: { fontWeight: 800, fontSize: "1rem", color: colors.inkPrimary }, children: m.crop_ko }), _jsx("span", { style: { fontSize: "0.72rem", color: colors.inkMuted, fontFamily: "monospace" }, children: m.crop_en }), _jsx("span", { style: badge(m.status === "loaded"), children: m.status === "loaded" ? "로드됨" : "모델 없음" }), m.model_type && (_jsx("span", { style: { fontSize: "0.72rem", background: colors.chartwellBlueBg, color: colors.chartwellBlue, borderRadius: radius.badge, padding: "2px 8px", fontWeight: 600 }, children: m.model_type === "xgb_lgb_ensemble" ? "XGB+LGB" : m.model_type }))] }), m.feature_count != null && (_jsxs("span", { style: { fontSize: "0.78rem", color: colors.inkMuted }, children: ["\uD53C\uCC98 ", m.feature_count, "\uAC1C"] }))] }), m.status === "loaded" && (_jsx("div", { style: { padding: "16px 20px", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 12 }, children: [
                                            { label: "훈련 R²", value: m.train_r2?.toFixed(3), color: r2Color(m.train_r2) },
                                            { label: "훈련 MAPE", value: m.train_mape != null ? `${m.train_mape.toFixed(1)}%` : null, color: colors.inkPrimary },
                                            { label: "검증 R²", value: m.test_r2?.toFixed(3), color: r2Color(m.test_r2) },
                                            { label: "검증 MAPE", value: m.test_mape != null ? `${m.test_mape.toFixed(1)}%` : null, color: colors.inkPrimary },
                                            { label: "학습 행수", value: m.n_train?.toLocaleString(), color: colors.inkPrimary },
                                            { label: "검증 행수", value: m.n_test?.toLocaleString(), color: colors.inkPrimary },
                                        ].map(({ label, value, color }) => (_jsxs("div", { style: { background: colors.canvasFog, borderRadius: 8, padding: "10px 12px" }, children: [_jsx("p", { style: { fontSize: "0.72rem", color: colors.inkMuted, marginBottom: 4 }, children: label }), _jsx("p", { style: { fontSize: "1rem", fontWeight: 800, color }, children: value ?? "—" })] }, label))) })), m.status === "loaded" && m.opt_temp != null && (_jsxs("div", { style: {
                                            margin: "0 20px 16px", padding: "12px 14px",
                                            background: "#f0fdf4", borderRadius: 8,
                                            border: "1px solid #86efac",
                                            fontSize: "0.82rem", color: colors.inkSecondary,
                                            display: "flex", flexWrap: "wrap", gap: "0 24px",
                                        }, children: [_jsxs("span", { children: ["\uD83C\uDF21\uFE0F \uCD5C\uC801 \uC628\uB3C4 ", _jsxs("strong", { style: { color: colors.inkPrimary }, children: [m.opt_temp, "\u00B0C"] })] }), _jsxs("span", { children: ["\uD83D\uDCA7 \uCD5C\uC801 \uC2B5\uB3C4 ", _jsxs("strong", { style: { color: colors.inkPrimary }, children: [m.opt_humid, "%"] })] }), _jsxs("span", { children: ["\uD83C\uDF3F \uCD5C\uC801 CO\u2082 ", _jsxs("strong", { style: { color: colors.inkPrimary }, children: [m.opt_co2, " ppm"] })] }), m.income_6m_krw != null && (_jsxs("span", { children: ["\uD83D\uDCB0 6\uAC1C\uC6D4 \uC608\uCE21 \uC18C\uB4DD ", _jsxs("strong", { style: { color: colors.successGreen }, children: [Math.round(m.income_6m_krw / 10000).toLocaleString(), "\uB9CC\uC6D0"] })] }))] }))] }, m.crop_ko))) })), section === "sources" && (_jsx("div", { style: { display: "flex", flexDirection: "column", gap: 12 }, children: sources.length === 0
                            ? _jsx("div", { style: { textAlign: "center", padding: 40, color: colors.inkMuted }, children: "\uBD88\uB7EC\uC624\uB294 \uC911\u2026" })
                            : sources.map(s => (_jsxs("div", { style: { ...card, padding: "16px 20px" }, children: [_jsxs("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }, children: [_jsxs("div", { style: { display: "flex", alignItems: "center", gap: 10 }, children: [_jsx("span", { style: {
                                                            width: 8, height: 8, borderRadius: "50%",
                                                            background: s.connected ? colors.successGreen : colors.inkMuted,
                                                            display: "inline-block", flexShrink: 0,
                                                        } }), _jsx("span", { style: { fontWeight: 700, fontSize: "1rem", color: colors.inkPrimary }, children: s.label_ko }), _jsx("span", { style: { fontSize: "0.75rem", color: s.connected ? colors.successGreen : colors.inkMuted }, children: s.connected ? "연결됨" : "미연결" })] }), _jsxs("span", { style: { fontSize: "0.875rem", fontWeight: 700, color: s.completeness_pct >= 80 ? colors.successGreen : colors.warningAmber }, children: [s.completeness_pct, "%"] })] }), _jsx("div", { style: { height: 6, background: colors.canvasFog, borderRadius: 9999, overflow: "hidden" }, children: _jsx("div", { style: {
                                                height: "100%", borderRadius: 9999, transition: "width 600ms",
                                                width: `${s.completeness_pct}%`,
                                                background: s.completeness_pct >= 80 ? colors.successGreen : colors.warningAmber,
                                            } }) })] }, s.source_id))) })), section === "registry" && (_jsx("div", { style: { ...card, overflow: "hidden" }, children: _jsxs("table", { style: { width: "100%", borderCollapse: "collapse" }, children: [_jsx("thead", { children: _jsx("tr", { style: { background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }, children: ["정규명", "표시명", "단위", "결측처리", "연결 소스"].map(h => (_jsx("th", { style: th, children: h }, h))) }) }), _jsx("tbody", { children: registry.length === 0
                                        ? _jsx("tr", { children: _jsx("td", { colSpan: 5, style: { padding: 40, textAlign: "center", color: colors.inkMuted }, children: "\uBD88\uB7EC\uC624\uB294 \uC911\u2026" }) })
                                        : registry.map((v, i) => (_jsxs("tr", { style: { borderBottom: i < registry.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }, children: [_jsx("td", { style: { ...td, fontFamily: "monospace", color: colors.chartwellBlue }, children: v.canonical_name }), _jsx("td", { style: { ...td, color: colors.inkPrimary, fontWeight: 500 }, children: v.display_name_ko }), _jsx("td", { style: { ...td, fontFamily: "monospace", color: colors.inkMuted }, children: v.unit }), _jsx("td", { style: td, children: _jsx("span", { style: { background: colors.canvasFog, borderRadius: 4, padding: "2px 8px", fontSize: "0.75rem", fontFamily: "monospace", color: colors.inkSecondary }, children: v.impute_strategy }) }), _jsx("td", { style: td, children: _jsx("div", { style: { display: "flex", gap: 5, flexWrap: "wrap" }, children: v.sources.map(src => (_jsxs("span", { style: {
                                                                background: colors.chartwellBlueBg, color: colors.chartwellBlue,
                                                                borderRadius: radius.badge, padding: "2px 8px",
                                                                fontSize: "0.7rem", fontWeight: 600,
                                                            }, children: [src.source_id, src.transform_expr && _jsxs("span", { style: { opacity: 0.7, marginLeft: 3 }, children: ["(", src.transform_expr, ")"] })] }, src.source_id + src.source_field))) }) })] }, v.canonical_name))) })] }) })), section === "pipeline" && (_jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 16 }, children: [_jsx("div", { style: { display: "flex", justifyContent: "flex-end" }, children: _jsx("button", { onClick: handleTrigger, disabled: triggering || triggered, style: {
                                        background: triggered ? colors.successGreen : colors.chartwellBlue,
                                        color: colors.cloudWhite, border: "none",
                                        borderRadius: radius.button, padding: "10px 24px",
                                        fontSize: "0.9375rem", fontWeight: 700,
                                        cursor: triggering || triggered ? "not-allowed" : "pointer",
                                        minHeight: 44, transition: "background 200ms",
                                    }, children: triggered ? "✓ 대기 중" : triggering ? "처리 중…" : "수동 재학습 트리거" }) }), _jsx("div", { style: { ...card, overflow: "hidden" }, children: _jsxs("table", { style: { width: "100%", borderCollapse: "collapse" }, children: [_jsx("thead", { children: _jsx("tr", { style: { background: colors.canvasFog, borderBottom: `1px solid ${colors.stoneBorder}` }, children: ["실행 ID", "트리거", "상태", "훈련 R²", "검증 R²", "학습행", "검증행", "배포"].map(h => (_jsx("th", { style: th, children: h }, h))) }) }), _jsx("tbody", { children: runs.length === 0
                                                ? _jsx("tr", { children: _jsx("td", { colSpan: 8, style: { padding: 40, textAlign: "center", color: colors.inkMuted }, children: "\uBD88\uB7EC\uC624\uB294 \uC911\u2026" }) })
                                                : runs.map((r, i) => {
                                                    const m = r.metrics_after;
                                                    return (_jsxs("tr", { style: { borderBottom: i < runs.length - 1 ? `1px solid ${colors.stoneBorder}` : "none" }, children: [_jsx("td", { style: { ...td, fontFamily: "monospace", fontSize: "0.8rem", color: colors.inkMuted }, children: r.run_id }), _jsx("td", { style: { ...td, color: colors.inkSecondary }, children: r.trigger === "scheduled" ? "자동" : r.trigger === "scripted" ? "스크립트" : "수동" }), _jsx("td", { style: td, children: _jsx("span", { style: badge(r.status === "success"), children: r.status === "success" ? "완료" : r.status === "running" ? "실행 중" : "실패" }) }), _jsx("td", { style: { ...td, fontWeight: 700, color: r2Color(m?.train_r2 ?? null) }, children: m?.train_r2 != null ? m.train_r2.toFixed(3) : "—" }), _jsx("td", { style: { ...td, fontWeight: 700, color: r2Color(m?.test_r2 ?? null) }, children: m?.test_r2 != null ? m.test_r2.toFixed(3) : "—" }), _jsx("td", { style: { ...td, color: colors.inkMuted }, children: m?.n_train != null ? m.n_train.toLocaleString() : "—" }), _jsx("td", { style: { ...td, color: colors.inkMuted }, children: m?.n_test != null ? m.n_test.toLocaleString() : "—" }), _jsx("td", { style: td, children: r.deployed === null ? _jsx("span", { style: { color: colors.inkMuted }, children: "\u2014" })
                                                                    : r.deployed
                                                                        ? _jsx("span", { style: { color: colors.successGreen, fontWeight: 700 }, children: "\uBC30\uD3EC\uB428" })
                                                                        : _jsx("span", { style: { color: colors.dangerRed }, children: "\uBBF8\uBC30\uD3EC" }) })] }, r.run_id));
                                                }) })] }) })] }))] }), _jsx("style", { children: `
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        button:focus-visible { outline: 3px solid ${colors.chartwellBlueBg}; outline-offset: 2px; }
        @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
      ` })] }));
}
