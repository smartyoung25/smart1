import React, { useState } from "react";
import { FarmerDashboard } from "./pages/FarmerDashboard";
import { AdminDashboard } from "./pages/AdminDashboard";
import { colors } from "./design-system/tokens";

/**
 * App — top-level router.
 *
 * URL 구조:
 *   /                     → FarmerDashboard (farm_001)
 *   /farms/:farmId        → FarmerDashboard (지정 농가)
 *   /admin                → AdminDashboard
 *
 * React Router v6가 설치되어 있으면 BrowserRouter를 사용한다.
 * 없으면 간단한 hash-based fallback으로 동작한다.
 */

type Route = { type: "farmer"; farmId: string } | { type: "admin" };

function parseRoute(): Route {
  const hash = window.location.hash.replace("#", "") || window.location.pathname;
  if (hash.startsWith("/admin")) return { type: "admin" };
  const farmMatch = hash.match(/\/farms\/([^/]+)/);
  if (farmMatch) return { type: "farmer", farmId: farmMatch[1] };
  return { type: "farmer", farmId: "farm_001" };
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute);

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

  return (
    <div style={{ fontFamily: "'Inter', sans-serif" }}>
      {/* Dev navigation bar — hidden in production via VITE_HIDE_DEVNAV=true */}
      {import.meta.env.VITE_HIDE_DEVNAV !== "true" && (
        <DevNav current={route} onNavigate={setRoute} />
      )}

      {route.type === "farmer" && <FarmerDashboard farmId={route.farmId} />}
      {route.type === "admin"  && <AdminDashboard />}
    </div>
  );
}

// ── Dev navigation bar ────────────────────────────────────────────────────────

const FARM_IDS = ["farm_001", "farm_002", "farm_003", "farm_004", "farm_005"];

function DevNav({
  current,
  onNavigate,
}: {
  current: Route;
  onNavigate: (r: Route) => void;
}) {
  return (
    <div style={{
      position: "fixed", bottom: "72px", right: "12px", zIndex: 9999,
      background: colors.inkPrimary, borderRadius: "12px",
      padding: "8px", display: "flex", flexDirection: "column", gap: "4px",
      boxShadow: "0 4px 20px rgba(0,0,0,.3)",
    }}>
      <span style={{ fontSize: "0.65rem", color: colors.inkMuted, padding: "0 4px", letterSpacing: "0.08em" }}>DEV</span>
      {FARM_IDS.map((id) => (
        <button
          key={id}
          onClick={() => onNavigate({ type: "farmer", farmId: id })}
          style={{
            background: current.type === "farmer" && (current as any).farmId === id
              ? colors.chartwellBlue : "rgba(255,255,255,0.1)",
            color: colors.cloudWhite,
            border: "none", borderRadius: "8px",
            padding: "4px 10px", fontSize: "0.75rem",
            cursor: "pointer", whiteSpace: "nowrap",
          }}
        >
          {id}
        </button>
      ))}
      <button
        onClick={() => onNavigate({ type: "admin" })}
        style={{
          background: current.type === "admin" ? colors.chartwellBlue : "rgba(255,255,255,0.1)",
          color: colors.cloudWhite,
          border: "none", borderRadius: "8px",
          padding: "4px 10px", fontSize: "0.75rem",
          cursor: "pointer",
        }}
      >
        관리자
      </button>
    </div>
  );
}
