/**
 * useFarm — SWR-based hooks for smart farm API endpoints
 *
 * 각 훅은 자동 10분 polling + 에러 처리를 포함한다.
 */
import useSWR from "swr";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const REFRESH_INTERVAL = 10 * 60 * 1000; // 10분

// ── Types (API 응답과 1:1 매핑) ──────────────────────────────────────────────

export interface Summary {
  farm_id: string;
  updated_at: string;
  alert_count: number;
  harvest_days_remaining: number | null;
  revenue_mtd_krw: number;
}

export interface RecommendationItem {
  rank: number;
  action_ko: string;
  profit_delta: number;
  revenue_delta: number;
  cost_delta: number;
  confidence: number;
  tier_action: "checklist" | "approval_required" | "auto";
  canonical_changes: Record<string, number>;
}

export interface RecommendationsResponse {
  farm_id: string;
  updated_at: string;
  recommendations: RecommendationItem[];
}

export interface EnvPoint {
  canonical_name: string;
  value: number;
  unit: string;
  quality_tag: string;
  imputed: boolean;
}

export interface EnvironmentResponse {
  farm_id: string;
  updated_at: string;
  measurements: EnvPoint[];
}

export interface HarvestForecast {
  farm_id: string;
  updated_at: string;
  predicted_date: string | null;
  predicted_yield_kg_m2: number | null;
  confidence: number;
  confidence_80pct?: { lower: number; upper: number };
}

export interface RevenueResponse {
  farm_id: string;
  updated_at: string;
  kamis_price_krw_kg: number;
  predicted_revenue_krw: number;
  predicted_cost_krw: number;
  predicted_profit_krw: number;
}

// ── Fetcher ──────────────────────────────────────────────────────────────────

async function fetcher<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API ${url} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ── SWR hooks with dynamic import fallback ────────────────────────────────────

type HookResult<T> = { data: T | undefined; error: Error | undefined; isLoading: boolean };

function useSWRFetch<T>(key: string | null): HookResult<T> {
  const { data, error } = useSWR<T>(key, fetcher, { refreshInterval: REFRESH_INTERVAL });
  return { data, error, isLoading: !data && !error };
}

// ── Public hooks ──────────────────────────────────────────────────────────────

export function useSummary(farmId: string): HookResult<Summary> {
  return useSWRFetch<Summary>(`${API_BASE}/api/farms/${farmId}/summary`);
}

export function useRecommendations(farmId: string): HookResult<RecommendationsResponse> {
  return useSWRFetch<RecommendationsResponse>(`${API_BASE}/api/farms/${farmId}/recommendations`);
}

export function useEnvironment(farmId: string): HookResult<EnvironmentResponse> {
  return useSWRFetch<EnvironmentResponse>(`${API_BASE}/api/farms/${farmId}/environment`);
}

export function useHarvest(farmId: string): HookResult<HarvestForecast> {
  return useSWRFetch<HarvestForecast>(`${API_BASE}/api/farms/${farmId}/harvest`);
}

export function useRevenue(farmId: string): HookResult<RevenueResponse> {
  return useSWRFetch<RevenueResponse>(`${API_BASE}/api/farms/${farmId}/revenue`);
}

// ── Mutation helper ──────────────────────────────────────────────────────────

export async function applyRecommendation(
  farmId: string,
  rank: number,
  confirmed: boolean,
): Promise<{ status: string; message_ko: string; checklist_url?: string }> {
  const res = await fetch(`${API_BASE}/api/farms/${farmId}/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rank, confirmed }),
  });
  if (!res.ok) throw new Error(`Apply failed: ${res.status}`);
  return res.json();
}
