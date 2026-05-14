/**
 * useFarm — SWR-based hooks for smart farm API endpoints
 *
 * 각 훅은 자동 10분 polling + 에러 처리를 포함한다.
 */
import useSWR from "swr";
const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const REFRESH_INTERVAL = 10 * 60 * 1000; // 10분
// ── Fetcher ──────────────────────────────────────────────────────────────────
async function fetcher(url) {
    const res = await fetch(url);
    if (!res.ok)
        throw new Error(`API ${url} → ${res.status}`);
    return res.json();
}
function useSWRFetch(key) {
    const { data, error } = useSWR(key, fetcher, { refreshInterval: REFRESH_INTERVAL });
    return { data, error, isLoading: !data && !error };
}
// ── Public hooks ──────────────────────────────────────────────────────────────
export function useSummary(farmId) {
    return useSWRFetch(`${API_BASE}/api/farms/${farmId}/summary`);
}
export function useRecommendations(farmId) {
    return useSWRFetch(`${API_BASE}/api/farms/${farmId}/recommendations`);
}
export function useEnvironment(farmId) {
    return useSWRFetch(`${API_BASE}/api/farms/${farmId}/environment`);
}
export function useHarvest(farmId) {
    return useSWRFetch(`${API_BASE}/api/farms/${farmId}/harvest`);
}
export function useRevenue(farmId) {
    return useSWRFetch(`${API_BASE}/api/farms/${farmId}/revenue`);
}
// ── Mutation helper ──────────────────────────────────────────────────────────
export async function applyRecommendation(farmId, rank, confirmed) {
    const res = await fetch(`${API_BASE}/api/farms/${farmId}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rank, confirmed }),
    });
    if (!res.ok)
        throw new Error(`Apply failed: ${res.status}`);
    return res.json();
}
