"""
Deterministic unit tests for Phase 1 perception expansion primitives.

These tests ensure byte-stable, reproducible output for:
- delta_z_mean (drift acceleration)
- z_std_std (vol-of-vol)
- delta_vol_norm (volume momentum)

Changing the expected values here requires a court note explaining why.
"""

import pytest
from synthdesk.listener.price_listener import (
    PriceTracker,
    VOL_OF_VOL_WINDOW,
    VOLUME_EWMA_ALPHA,
    _quantize_z,
)


class TestPhase1Primitives:
    """Deterministic tests for phase-1 primitives."""

    def test_constants_frozen(self):
        """Verify frozen constants match spec."""
        assert VOL_OF_VOL_WINDOW == 10, "VOL_OF_VOL_WINDOW changed without court approval"
        assert abs(VOLUME_EWMA_ALPHA - 2.0 / 21) < 1e-10, "VOLUME_EWMA_ALPHA changed"

    def test_quantization_deterministic(self):
        """Verify quantization is deterministic."""
        assert _quantize_z(0.123456789) == 0.123457
        assert _quantize_z(-0.000001234) == -0.000001
        assert _quantize_z(0.0) == 0.0

    def test_delta_z_mean_deterministic(self):
        """
        Fixed price series -> expected delta_z_mean values.

        This test locks the computation to prevent silent refactors.
        """
        tracker = PriceTracker("TEST", window=60)

        # Fixed price series: linear increase
        prices = [100.0 + i * 0.1 for i in range(15)]

        results = []
        for p in prices:
            metrics = tracker.update(p)
            results.append(metrics.get("delta_z_mean"))

        # First tick: None (no history)
        assert results[0] is None

        # Second tick: None (need 2 z_mean values)
        assert results[1] is None

        # Third tick onwards: should have values
        # Lock specific values for determinism
        assert results[2] == pytest.approx(-0.000497, abs=1e-6)
        assert results[10] == pytest.approx(-0.000482, abs=1e-6)

    def test_z_std_std_deterministic(self):
        """
        Fixed price series -> expected z_std_std values.

        z_std_std requires VOL_OF_VOL_WINDOW (10) observations.
        """
        tracker = PriceTracker("TEST", window=60)

        prices = [100.0 + i * 0.1 for i in range(15)]

        results = []
        for p in prices:
            metrics = tracker.update(p)
            results.append(metrics.get("z_std_std"))

        # First 9 ticks: None (insufficient history)
        for i in range(VOL_OF_VOL_WINDOW - 1):
            assert results[i] is None, f"Expected None at tick {i}"

        # Tick 10 onwards: should have values
        assert results[VOL_OF_VOL_WINDOW - 1] is None  # tick 9 (0-indexed)
        assert results[VOL_OF_VOL_WINDOW] == pytest.approx(0.000879, abs=1e-6)  # tick 10

    def test_delta_vol_norm_deterministic(self):
        """
        Fixed price + volume series -> expected delta_vol_norm values.
        """
        tracker = PriceTracker("TEST", window=60)

        prices = [100.0 + i * 0.1 for i in range(15)]
        volumes = [1000.0 + i * 50.0 for i in range(15)]

        results = []
        for p, v in zip(prices, volumes):
            metrics = tracker.update(p, volume=v)
            results.append(metrics.get("delta_vol_norm"))

        # First tick: 0 (volume == ewma_volume after seeding)
        # Actually first tick has no return, so metrics are minimal
        assert results[1] is not None  # Second tick should have value

        # Lock specific values
        assert results[10] == pytest.approx(0.231552, abs=1e-6)
        assert results[14] == pytest.approx(0.25525, abs=1e-5)

    def test_delta_vol_norm_none_without_volume(self):
        """delta_vol_norm should be None when volume not provided."""
        tracker = PriceTracker("TEST", window=60)

        for i in range(15):
            metrics = tracker.update(100.0 + i * 0.1)  # No volume
            assert metrics.get("delta_vol_norm") is None

    def test_state_persistence(self, tmp_path):
        """Verify state save/load preserves phase-1 state."""
        tracker1 = PriceTracker("TEST", window=60)

        # Run some updates
        for i in range(15):
            tracker1.update(100.0 + i * 0.1, volume=1000.0 + i * 50.0)

        # Save state
        state_path = tmp_path / "state.json"
        tracker1.save_state(state_path)

        # Load into new tracker
        tracker2 = PriceTracker("TEST", window=60)
        tracker2.load_state(state_path)

        # Verify state matches
        assert list(tracker1.z_std_history) == list(tracker2.z_std_history)
        assert list(tracker1.volume_history) == list(tracker2.volume_history)
        assert tracker1.ewma_volume == tracker2.ewma_volume
        assert tracker1.ewma_volume_initialized == tracker2.ewma_volume_initialized

        # Next update should produce identical results
        metrics1 = tracker1.update(101.5, volume=1750.0)
        metrics2 = tracker2.update(101.5, volume=1750.0)

        assert metrics1["delta_z_mean"] == metrics2["delta_z_mean"]
        assert metrics1["z_std_std"] == metrics2["z_std_std"]
        assert metrics1["delta_vol_norm"] == metrics2["delta_vol_norm"]


class TestPhase1EdgeCases:
    """Edge case tests for phase-1 primitives."""

    def test_zero_volume(self):
        """Zero volume should not cause division by zero."""
        tracker = PriceTracker("TEST", window=60)

        # First update with zero volume
        metrics = tracker.update(100.0, volume=0.0)
        # Should seed ewma_volume to 0, delta_vol_norm will be None (0/0)

        # Second update with positive volume
        metrics = tracker.update(100.1, volume=100.0)
        # ewma_volume is still ~0 from seeding, division might fail
        # This should handle gracefully
        assert "delta_vol_norm" in metrics

    def test_negative_volume_ignored(self):
        """Negative volume should be treated as missing."""
        tracker = PriceTracker("TEST", window=60)

        metrics = tracker.update(100.0, volume=-100.0)
        assert metrics.get("delta_vol_norm") is None

    def test_single_price_minimal_output(self):
        """Single price update should return minimal metrics."""
        tracker = PriceTracker("TEST", window=60)

        metrics = tracker.update(100.0)

        assert metrics["z_mean"] == 0.0
        assert metrics["z_std"] == 0.0
        assert metrics.get("delta_z_mean") is None
        assert metrics.get("z_std_std") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
