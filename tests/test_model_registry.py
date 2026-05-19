"""model_registry.py 단위 테스트 — 파일시스템은 tmp_path로 격리."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

import pipeline.model_registry as reg_mod


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """레지스트리 파일과 아티팩트 디렉터리를 임시 경로로 격리."""
    monkeypatch.setattr(reg_mod, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(reg_mod, "REGISTRY_FILE", tmp_path / "registry.json")
    yield tmp_path


def _make_artifact(tmp_path, crop_en: str, files: list[str] | None = None):
    """테스트용 아티팩트 파일 생성."""
    canon = tmp_path / "artifacts" / crop_en
    canon.mkdir(parents=True, exist_ok=True)
    for fname in (files or ["stage2_yield.pkl", "pipeline_meta.json"]):
        (canon / fname).write_text("dummy", encoding="utf-8")
    return canon


def _make_meta(tmp_path, crop_en: str, mape: float = 5.0, cv_r2: float = 0.88):
    """pipeline_meta.json 생성."""
    canon = tmp_path / "artifacts" / crop_en
    canon.mkdir(parents=True, exist_ok=True)
    meta = {
        "stage2": {"mape": mape, "cv_r2_mean": cv_r2, "gate_passed": True},
        "stage3": {"mape": mape * 1.2, "gate_passed": True},
    }
    (canon / "pipeline_meta.json").write_text(json.dumps(meta), encoding="utf-8")


# ── snapshot_before_retrain ───────────────────────────────────────────────────

class TestSnapshot:
    def test_returns_none_when_no_artifact(self, isolated_registry):
        result = reg_mod.snapshot_before_retrain("strawberry")
        assert result is None

    def test_creates_version_dir(self, isolated_registry):
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry")
        ver = reg_mod.snapshot_before_retrain("strawberry")
        assert ver == 1
        assert (tmp / "artifacts" / ".versions" / "strawberry" / "v1").exists()

    def test_snapshot_increments_version(self, isolated_registry):
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry")
        v1 = reg_mod.snapshot_before_retrain("strawberry")
        v2 = reg_mod.snapshot_before_retrain("strawberry")
        assert v1 == 1
        assert v2 == 2

    def test_snapshot_excludes_version_subdirs(self, isolated_registry):
        """v*/ 서브디렉터리는 스냅샷에 포함되지 않아야 함 (중첩 방지)."""
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry")
        reg_mod.snapshot_before_retrain("strawberry")   # v1 생성
        reg_mod.snapshot_before_retrain("strawberry")   # v2에 v1이 중첩되지 않아야 함
        v2_dir = tmp / "artifacts" / ".versions" / "strawberry" / "v2"
        assert not (v2_dir / "v1").exists()


# ── register_version ──────────────────────────────────────────────────────────

class TestRegisterVersion:
    def test_registers_first_version(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "strawberry", mape=5.0)
        ver = reg_mod.register_version("strawberry", gate_passed=True)
        assert ver == 1

    def test_active_version_set_on_gate_pass(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "strawberry")
        reg_mod.register_version("strawberry", gate_passed=True)
        reg = reg_mod._load_registry()
        assert reg["strawberry"]["active_version"] == 1

    def test_active_version_not_set_on_gate_fail(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "strawberry")
        reg_mod.register_version("strawberry", gate_passed=False)
        reg = reg_mod._load_registry()
        # 첫 버전이 gate fail이면 active는 None
        assert reg["strawberry"]["active_version"] is None

    def test_reads_mape_from_meta(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "tomato", mape=6.5, cv_r2=0.91)
        reg_mod.register_version("tomato", gate_passed=True)
        versions = reg_mod.get_versions("tomato")
        assert versions[0]["mape_stage2"] == pytest.approx(6.5)
        assert versions[0]["cv_r2"] == pytest.approx(0.91)

    def test_manual_mape_overrides_meta(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "tomato", mape=6.5)
        reg_mod.register_version("tomato", mape_stage2=3.2, gate_passed=True)
        versions = reg_mod.get_versions("tomato")
        assert versions[0]["mape_stage2"] == pytest.approx(3.2)

    def test_version_increments(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "strawberry")
        v1 = reg_mod.register_version("strawberry", gate_passed=True)
        _make_meta(tmp, "strawberry", mape=4.0)
        v2 = reg_mod.register_version("strawberry", gate_passed=True)
        assert v1 == 1
        assert v2 == 2

    def test_previous_versions_deactivated(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "strawberry")
        reg_mod.register_version("strawberry", gate_passed=True)
        reg_mod.register_version("strawberry", gate_passed=True)
        versions = reg_mod.get_versions("strawberry")  # 최신순
        assert versions[0]["is_active"] is True
        assert versions[1]["is_active"] is False


# ── rollback ──────────────────────────────────────────────────────────────────

class TestRollback:
    def test_rollback_restores_files(self, isolated_registry):
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry", files=["stage2_yield.pkl"])
        snap = reg_mod.snapshot_before_retrain("strawberry")

        # 아티팩트 변경
        (tmp / "artifacts" / "strawberry" / "stage2_yield.pkl").write_text("new_content")

        _make_meta(tmp, "strawberry")
        reg_mod.register_version("strawberry", gate_passed=True, snapshot_version=snap)

        ok = reg_mod.rollback("strawberry", target_version=snap)
        assert ok is True

        content = (tmp / "artifacts" / "strawberry" / "stage2_yield.pkl").read_text()
        assert content == "dummy"

    def test_rollback_updates_active_version(self, isolated_registry):
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry")
        snap = reg_mod.snapshot_before_retrain("strawberry")
        _make_meta(tmp, "strawberry")
        reg_mod.register_version("strawberry", gate_passed=True, snapshot_version=snap)
        reg_mod.rollback("strawberry", target_version=snap)

        reg = reg_mod._load_registry()
        assert reg["strawberry"]["active_version"] == snap

    def test_rollback_returns_false_when_no_snapshot(self, isolated_registry):
        _make_meta(isolated_registry, "strawberry")
        reg_mod.register_version("strawberry", gate_passed=True)
        ok = reg_mod.rollback("strawberry", target_version=99)
        assert ok is False

    def test_rollback_returns_false_when_no_history(self, isolated_registry):
        ok = reg_mod.rollback("strawberry")
        assert ok is False


# ── compare_versions ──────────────────────────────────────────────────────────

class TestCompareVersions:
    def test_compare_returns_delta(self, isolated_registry):
        tmp = isolated_registry
        _make_meta(tmp, "strawberry", mape=8.0, cv_r2=0.80)
        reg_mod.register_version("strawberry", gate_passed=True)
        _make_meta(tmp, "strawberry", mape=5.0, cv_r2=0.90)
        reg_mod.register_version("strawberry", gate_passed=True)

        result = reg_mod.compare_versions("strawberry", 1, 2)
        assert "delta" in result
        assert result["delta"]["mape_stage2"] == pytest.approx(5.0 - 8.0)
        assert result["delta"]["cv_r2"]        == pytest.approx(0.90 - 0.80)

    def test_compare_invalid_version_returns_error(self, isolated_registry):
        result = reg_mod.compare_versions("strawberry", 1, 99)
        assert "error" in result


# ── cleanup_old_snapshots ─────────────────────────────────────────────────────

class TestCleanup:
    def test_cleanup_removes_old_versions(self, isolated_registry):
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry")
        _make_meta(tmp, "strawberry")

        # 7개 스냅샷 생성
        for _ in range(7):
            reg_mod.snapshot_before_retrain("strawberry")
            reg_mod.register_version("strawberry", gate_passed=True)

        removed = reg_mod.cleanup_old_snapshots("strawberry", keep_n=5)
        assert removed >= 1

    def test_cleanup_keeps_active_version(self, isolated_registry):
        tmp = isolated_registry
        _make_artifact(tmp, "strawberry")
        _make_meta(tmp, "strawberry")

        for _ in range(3):
            reg_mod.snapshot_before_retrain("strawberry")
            reg_mod.register_version("strawberry", gate_passed=True)

        active = reg_mod._load_registry()["strawberry"]["active_version"]
        reg_mod.cleanup_old_snapshots("strawberry", keep_n=1)

        reg = reg_mod._load_registry()
        assert reg["strawberry"]["active_version"] == active
