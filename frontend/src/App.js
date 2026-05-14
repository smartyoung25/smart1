import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import React, { useState } from "react";
import { FarmerDashboard } from "./pages/FarmerDashboard";
import { AdminDashboard } from "./pages/AdminDashboard";
import { colors } from "./design-system/tokens";
function parseRoute() {
    const hash = window.location.hash.replace("#", "") || window.location.pathname;
    if (hash.startsWith("/admin"))
        return { type: "admin" };
    const farmMatch = hash.match(/\/farms\/([^/]+)/);
    if (farmMatch)
        return { type: "farmer", farmId: farmMatch[1] };
    return { type: "farmer", farmId: "farm_001" };
}
export default function App() {
    const [route, setRoute] = useState(parseRoute);
    // Listen to hash changes for SPA navigation
    React.useEffect(() => {
        const handler = () => setRoute(parseRoute());
        window.addEventListener("hashchange", handler);
        window.addEventListener("popstate", handler);
        return () => {
            window.removeEventListener("hashchange", handler);
            window.removeEventListener("popstate", handler);
        };
    }, []);
    return (_jsxs("div", { style: { fontFamily: "'Inter', sans-serif" }, children: [import.meta.env.VITE_HIDE_DEVNAV !== "true" && (_jsx(DevNav, { current: route, onNavigate: setRoute })), route.type === "farmer" && _jsx(FarmerDashboard, { farmId: route.farmId }), route.type === "admin" && _jsx(AdminDashboard, {})] }));
}
// ── Dev navigation bar ────────────────────────────────────────────────────────
const FARM_IDS = ["farm_001", "farm_002", "farm_003", "farm_004", "farm_005"];
function DevNav({ current, onNavigate, }) {
    return (_jsxs("div", { style: {
            position: "fixed", bottom: "72px", right: "12px", zIndex: 9999,
            background: colors.inkPrimary, borderRadius: "12px",
            padding: "8px", display: "flex", flexDirection: "column", gap: "4px",
            boxShadow: "0 4px 20px rgba(0,0,0,.3)",
        }, children: [_jsx("span", { style: { fontSize: "0.65rem", color: colors.inkMuted, padding: "0 4px", letterSpacing: "0.08em" }, children: "DEV" }), FARM_IDS.map((id) => (_jsx("button", { onClick: () => onNavigate({ type: "farmer", farmId: id }), style: {
                    background: current.type === "farmer" && current.farmId === id
                        ? colors.chartwellBlue : "rgba(255,255,255,0.1)",
                    color: colors.cloudWhite,
                    border: "none", borderRadius: "8px",
                    padding: "4px 10px", fontSize: "0.75rem",
                    cursor: "pointer", whiteSpace: "nowrap",
                }, children: id }, id))), _jsx("button", { onClick: () => onNavigate({ type: "admin" }), style: {
                    background: current.type === "admin" ? colors.chartwellBlue : "rgba(255,255,255,0.1)",
                    color: colors.cloudWhite,
                    border: "none", borderRadius: "8px",
                    padding: "4px 10px", fontSize: "0.75rem",
                    cursor: "pointer",
                }, children: "\uAD00\uB9AC\uC790" })] }));
}
