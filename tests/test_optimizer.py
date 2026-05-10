"""수익 최적화 엔진 단위 테스트"""
import pytest

from engine.farm_tier import FarmTier
from engine.what_if_simulator import EnvState, generate_candidates
from engine.profit_optimizer import optimize, MAX_RECOMMENDATIONS


BASE_ENV = {
    "temp_internal":  22.0,
    "humidity_int":   75.0,
    "co2_ppm":        900.0,
    "solar_rad":      300.0,
    "ec_dsm":         2.0,
}


class TestWhatIfSimulator:
    def test_generates_candidates(self):
        state = EnvState(farm_id="farm_001", values=BASE_ENV)
        candidates = generate_candidates(state)
        assert len(candidates) > 0

    def test_candidate_within_bounds(self):
        from engine.what_if_simulator import _BOUNDS
        state = EnvState(farm_id="farm_001", values=BASE_ENV)
        candidates = generate_candidates(state)
        for c in candidates:
            for var, new_val in c.changes.items():
                lo, hi = _BOUNDS.get(var, (-1e9, 1e9))
                assert lo <= new_val <= hi, f"{var}={new_val} out of [{lo}, {hi}]"

    def test_single_variable_per_candidate(self):
        state = EnvState(farm_id="farm_001", values=BASE_ENV)
        candidates = generate_candidates(state)
        for c in candidates:
            assert len(c.changes) == 1

    def test_description_ko_not_empty(self):
        state = EnvState(farm_id="farm_001", values=BASE_ENV)
        candidates = generate_candidates(state)
        for c in candidates:
            assert c.description_ko.strip() != ""

    def test_no_candidates_for_empty_env(self):
        state = EnvState(farm_id="farm_001", values={})
        candidates = generate_candidates(state)
        assert len(candidates) == 0


class TestProfitOptimizer:
    def _optimize(self, tier=FarmTier.MANUAL):
        state = EnvState(farm_id="farm_001", values=BASE_ENV)
        return optimize(
            farm_id="farm_001",
            tier=tier,
            current_env=state,
            horizon_days=30,
            area_m2=1000.0,
        )

    def test_returns_list(self):
        recs = self._optimize()
        assert isinstance(recs, list)

    def test_max_recommendations(self):
        recs = self._optimize()
        assert len(recs) <= MAX_RECOMMENDATIONS

    def test_sorted_by_profit_delta_descending(self):
        recs = self._optimize()
        deltas = [r.profit_delta for r in recs]
        assert deltas == sorted(deltas, reverse=True)

    def test_ranks_are_sequential(self):
        recs = self._optimize()
        for i, r in enumerate(recs, start=1):
            assert r.rank == i

    def test_tier_manual_action(self):
        recs = self._optimize(tier=FarmTier.MANUAL)
        for r in recs:
            assert r.tier_action == "checklist"

    def test_tier_semi_auto_action(self):
        recs = self._optimize(tier=FarmTier.SEMI_AUTO)
        for r in recs:
            assert r.tier_action == "approval_required"

    def test_tier_auto_action(self):
        recs = self._optimize(tier=FarmTier.AUTO)
        for r in recs:
            assert r.tier_action == "auto"

    def test_canonical_changes_not_empty(self):
        recs = self._optimize()
        for r in recs:
            assert len(r.canonical_changes) > 0
