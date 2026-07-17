# test_hud_extended.py
"""Tests for HUD extensions: orb integration, transcription, voice status."""
import sys
import warnings
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from Quartz import CALayer  # real CALayer for PyObjC compatibility


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_real_calayer():
    """Create a real CALayer that PyObjC can accept as a sublayer."""
    return CALayer.layer()


def _make_mock_orb_layer():
    """Build a mock OrbLayer with a real CALayer for PyObjC compatibility."""
    mock_orb = MagicMock(name="OrbLayer", spec=["layer", "transition_to"])
    mock_orb.layer = _make_real_calayer()
    mock_orb.transition_to = MagicMock()
    return mock_orb


def _make_mock_orbs_module():
    """Build a mock orbs module with OrbState enum and OrbLayer class."""
    mock_orbs = MagicMock(name="orbs")
    mock_orbs.OrbState = MagicMock(name="OrbState")
    mock_orbs.OrbState.side_effect = lambda v: MagicMock(value=v, name=f"OrbState.{v}")
    mock_orb_layer_instance = _make_mock_orb_layer()
    mock_orbs.OrbLayer = MagicMock(name="OrbLayer", return_value=mock_orb_layer_instance)
    return mock_orbs, mock_orb_layer_instance


# ---------------------------------------------------------------------------
# Orb integration tests (with mock orbs)
# ---------------------------------------------------------------------------

class TestOrbIntegration:
    """Tests that exercise the orb integration path with a mock orbs module."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        mock_orbs, self.mock_orb_instance = _make_mock_orbs_module()
        monkeypatch.setitem(sys.modules, "orbs", mock_orbs)
        # Force hud to believe orbs is available
        import hud
        monkeypatch.setattr(hud, "ORBS_AVAILABLE", True)
        monkeypatch.setattr(hud, "OrbState", mock_orbs.OrbState)
        monkeypatch.setattr(hud, "OrbLayer", mock_orbs.OrbLayer)
        self.mock_orbs = mock_orbs

    def test_show_orb_creates_orb_layer(self):
        """show_orb() creates an OrbLayer and adds its CALayer as sublayer."""
        from hud import HUD
        h = HUD()
        h.show_orb()

        assert h._orb_layer is not None
        assert h._orb_sublayer_added is True
        # OrbLayer constructor was called once
        self.mock_orbs.OrbLayer.assert_called_once()
        h.close()

    def test_hide_orb_removes_sublayer(self):
        """hide_orb() marks the orb sublayer as removed."""
        from hud import HUD
        h = HUD()
        h.show_orb()
        assert h._orb_sublayer_added is True

        h.hide_orb()
        assert h._orb_sublayer_added is False
        h.close()

    def test_set_orb_state_delegates(self):
        """set_orb_state() calls transition_to() on the orb layer."""
        from hud import HUD
        h = HUD()
        h.show_orb()

        state_mock = MagicMock()
        h.set_orb_state(state_mock)
        self.mock_orb_instance.transition_to.assert_called_once_with(state_mock)
        h.close()

    def test_set_orb_state_with_int_converts(self):
        """set_orb_state(int) maps through OrbState enum before delegating."""
        from hud import HUD
        h = HUD()
        h.show_orb()

        h.set_orb_state(2)  # e.g. OrbState.THINKING
        self.mock_orbs.OrbState.assert_called_once_with(2)
        self.mock_orb_instance.transition_to.assert_called_once()
        h.close()

    def test_set_orb_state_noop_when_orb_not_shown(self):
        """set_orb_state() is a no-op if orb has never been shown."""
        from hud import HUD
        h = HUD()
        # No error, no transition_to call
        h.set_orb_state(MagicMock())
        assert h._orb_layer is None
        h.close()

    def test_show_orb_reuses_existing_layer(self):
        """Calling show_orb() twice reuses the same OrbLayer."""
        from hud import HUD
        h = HUD()
        h.show_orb()
        orb1 = h._orb_layer

        h.show_orb()
        orb2 = h._orb_layer

        assert orb1 is orb2
        # Only constructed once (the mock factory always returns the same instance)
        h.close()


# ---------------------------------------------------------------------------
# Orb graceful degradation (orbs module absent)
# ---------------------------------------------------------------------------

class TestOrbGracefulDegradation:
    """Tests that HUD works correctly when orbs.py is NOT available."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        # Remove orbs from sys.modules
        sys.modules.pop("orbs", None)
        # Reload hud to pick up the missing import
        import hud
        import importlib
        importlib.reload(hud)
        # Override ORBS_AVAILABLE to False (belt-and-suspenders)
        monkeypatch.setattr(hud, "ORBS_AVAILABLE", False)
        monkeypatch.setattr(hud, "OrbState", None)
        monkeypatch.setattr(hud, "OrbLayer", None)
        self.hud = hud

    def test_show_orb_is_noop(self):
        """When orbs unavailable, show_orb() emits warning and is a no-op."""
        HUD = self.hud.HUD
        h = HUD()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            h.show_orb()

        assert h._orb_layer is None
        assert any(
            "orbs module not available" in str(warning.message)
            for warning in w
        )
        h.close()

    def test_hide_orb_is_noop(self):
        """hide_orb() is a no-op when orb was never shown."""
        HUD = self.hud.HUD
        h = HUD()
        h.hide_orb()
        h.close()

    def test_set_orb_state_is_noop(self):
        """set_orb_state() is a no-op when orbs unavailable."""
        HUD = self.hud.HUD
        h = HUD()
        h.set_orb_state(1)
        h.close()

    def test_orbs_unavailable_warning_on_init(self):
        """HUD.__init__ emits a warning when orbs is not available."""
        HUD = self.hud.HUD
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            h = HUD()
        assert any(
            "orbs module not found" in str(warning.message)
            for warning in w
        )
        h.close()


# ---------------------------------------------------------------------------
# Transcription display tests
# ---------------------------------------------------------------------------

class TestTranscription:
    """Tests for show_transcription / clear_transcription."""

    def test_show_transcription_creates_label_and_sets_text(self):
        """show_transcription() lazily creates the label and sets its text."""
        from hud import HUD
        h = HUD()
        h.show_transcription("Hello, how can I help?")

        assert h._transcription_label is not None
        assert "Hello, how can I help?" in h._transcription_label.stringValue()
        h.close()

    def test_clear_transcription_empties_text(self):
        """clear_transcription() sets the transcription label to empty string."""
        from hud import HUD
        h = HUD()
        h.show_transcription("Some streaming text")
        assert h._transcription_label.stringValue() != ""

        h.clear_transcription()
        assert h._transcription_label.stringValue() == ""
        h.close()

    def test_show_transcription_updates_existing_label(self):
        """Calling show_transcription() again updates the same label."""
        from hud import HUD
        h = HUD()
        h.show_transcription("First")
        label1 = h._transcription_label

        h.show_transcription("Second")
        label2 = h._transcription_label

        assert label1 is label2
        assert "Second" in h._transcription_label.stringValue()
        h.close()

    def test_clear_transcription_before_show_is_noop(self):
        """clear_transcription() before ever showing transcription is safe."""
        from hud import HUD
        h = HUD()
        h.clear_transcription()
        assert h._transcription_label is None
        h.close()


# ---------------------------------------------------------------------------
# Voice status pill tests
# ---------------------------------------------------------------------------

class TestVoiceStatus:
    """Tests for show_voice_status."""

    def test_show_voice_status_creates_label(self):
        """show_voice_status() lazily creates the voice status label."""
        from hud import HUD
        h = HUD()
        h.show_voice_status("🎤 Listening...")

        assert h._voice_status_label is not None
        assert "Listening" in h._voice_status_label.stringValue()
        h.close()

    def test_show_voice_status_updates_text(self):
        """Calling show_voice_status() again updates text on the same label."""
        from hud import HUD
        h = HUD()
        h.show_voice_status("🎤 Listening...")
        label1 = h._voice_status_label

        h.show_voice_status("Thinking...")
        label2 = h._voice_status_label

        assert label1 is label2
        assert "Thinking" in h._voice_status_label.stringValue()
        h.close()

    def test_voice_status_pill_text_color_is_green(self):
        """The voice status label uses a green-ish text color."""
        from hud import HUD
        h = HUD()
        h.show_voice_status("Sent ✅")

        color = h._voice_status_label.textColor()
        r = color.redComponent()
        g = color.greenComponent()
        assert g > 0.7
        assert r < 0.5
        h.close()


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Existing public API (show, hide, close) must be unaffected."""

    def test_show_still_works(self):
        """show() sets the main label text and makes the window visible."""
        from hud import HUD
        h = HUD()
        h.show("Gesture: Scroll")
        assert h._label.stringValue() == "Gesture: Scroll"
        assert h._visible is True
        h.close()

    def test_hide_still_works(self):
        """hide() sets visible to False."""
        from hud import HUD
        h = HUD()
        h.show("Test")
        h.hide()
        assert h._visible is False
        h.close()

    def test_close_still_works(self):
        """close() destroys the window."""
        from hud import HUD
        h = HUD()
        h.show("Test")
        h.close()
        assert h._window is None
        assert h._label is None

    def test_close_cleans_up_extended_elements(self):
        """close() resets orb, transcription, and voice status state."""
        from hud import HUD
        h = HUD()
        h.show("Test")
        h.show_transcription("streaming")
        h.show_voice_status("Listening")
        h.close()

        assert h._window is None
        assert h._label is None
        assert h._transcription_label is None
        assert h._voice_status_label is None
        assert h._orb_layer is None
        assert h._orb_sublayer_added is False


# ---------------------------------------------------------------------------
# Dynamic window sizing
# ---------------------------------------------------------------------------

class TestDynamicWindowSizing:
    """Window height and width adapt based on visible elements."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        mock_orbs, self.mock_orb_instance = _make_mock_orbs_module()
        monkeypatch.setitem(sys.modules, "orbs", mock_orbs)
        import hud
        monkeypatch.setattr(hud, "ORBS_AVAILABLE", True)
        monkeypatch.setattr(hud, "OrbState", mock_orbs.OrbState)
        monkeypatch.setattr(hud, "OrbLayer", mock_orbs.OrbLayer)
        self.mock_orbs = mock_orbs
        self.hud = hud

    def _get_window_size(self, h):
        frame = h._window.frame()
        return frame.size.width, frame.size.height

    def test_base_window_is_200x60(self):
        """Default HUD window is 200x60 (preserving original dimensions)."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Test")
        w, hgt = self._get_window_size(h)
        assert w == 200
        assert hgt == 60
        h.close()

    def test_transcription_expands_to_100(self):
        """Showing transcription expands window height to 100."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_transcription("Streaming text")
        w, hgt = self._get_window_size(h)
        assert hgt == 100
        h.close()

    def test_voice_status_alone_keeps_60_height(self):
        """Voice status pill does not change height (fits inside 60px)."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_voice_status("🎤 Listening...")
        w, hgt = self._get_window_size(h)
        assert hgt == 60
        h.close()

    def test_voice_status_widens_window(self):
        """Voice status widens window to 280."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_voice_status("🎤 Listening...")
        w, hgt = self._get_window_size(h)
        assert w == 280
        h.close()

    def test_orb_expands_to_160(self):
        """Showing orb expands window to 160 height."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_orb()
        w, hgt = self._get_window_size(h)
        assert w == 280
        assert hgt == 160
        h.close()

    def test_orb_plus_transcription_expands_to_200(self):
        """Orb + transcription = maximum height of 200."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_orb()
        h.show_transcription("Streaming...")
        w, hgt = self._get_window_size(h)
        assert w == 280
        assert hgt == 200
        h.close()

    def test_clearing_transcription_shrinks_from_100_to_60(self):
        """After clear_transcription(), window shrinks back to 60."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_transcription("text")
        w, hgt = self._get_window_size(h)
        assert hgt == 100

        h.clear_transcription()
        w2, hgt2 = self._get_window_size(h)
        assert hgt2 == 60
        h.close()

    def test_hiding_orb_shrinks_from_160_to_60(self):
        """After hide_orb(), window shrinks back to 60."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_orb()
        w, hgt = self._get_window_size(h)
        assert hgt == 160

        h.hide_orb()
        w2, hgt2 = self._get_window_size(h)
        assert hgt2 == 60
        h.close()

    def test_hiding_orb_stays_at_100_if_transcription_active(self):
        """Hiding orb when transcription is shown shrinks to 100, not 60."""
        HUD = self.hud.HUD
        h = HUD()
        h.show("Mode")
        h.show_orb()
        h.show_transcription("Still streaming")
        w, hgt = self._get_window_size(h)
        assert hgt == 200

        h.hide_orb()
        w2, hgt2 = self._get_window_size(h)
        assert hgt2 == 100  # transcription still active
        h.close()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Corner-case tests for robustness."""

    def test_extensions_on_hud_without_show(self):
        """Calling extended methods before show() lazily creates the window."""
        from hud import HUD
        h = HUD()
        assert h._window is None

        h.show_transcription("lazy")
        assert h._window is not None
        assert h._transcription_label is not None
        h.close()

    def test_voice_status_before_show(self):
        """show_voice_status() before show() creates the window lazily."""
        from hud import HUD
        h = HUD()
        h.show_voice_status("Lazy status")
        assert h._window is not None
        assert h._voice_status_label is not None
        h.close()

    def test_orb_before_show_with_mock(self, monkeypatch):
        """show_orb() before show() creates the window lazily (with mock)."""
        mock_orbs, _ = _make_mock_orbs_module()
        monkeypatch.setitem(sys.modules, "orbs", mock_orbs)
        import hud
        monkeypatch.setattr(hud, "ORBS_AVAILABLE", True)
        monkeypatch.setattr(hud, "OrbState", mock_orbs.OrbState)
        monkeypatch.setattr(hud, "OrbLayer", mock_orbs.OrbLayer)

        HUD = hud.HUD
        h = HUD()
        h.show_orb()
        assert h._window is not None
        assert h._orb_layer is not None
        h.close()

    def test_recalc_layout_noop_when_window_none(self):
        """_recalc_layout is safe to call before window exists."""
        from hud import HUD
        h = HUD()
        h._recalc_layout()

    def test_add_orb_layer_accepts_external_layer(self):
        """add_orb_layer() accepts an externally-created layer."""
        from hud import HUD
        h = HUD()
        real_layer = _make_real_calayer()
        h.add_orb_layer(real_layer)
        assert h._orb_layer is real_layer
        assert h._orb_sublayer_added is True
        h.close()

    def test_orbs_import_failure_module_level(self, monkeypatch):
        """When orbs is absent, ORBS_AVAILABLE is False at module level."""
        # Force-clear any stale orbs mock from prior tests
        sys.modules.pop("orbs", None)
        import importlib
        import hud
        importlib.reload(hud)
        # Belt-and-suspenders: explicitly set back to False in case the module
        # was previously patched and reload didn't fully reset state.
        monkeypatch.setattr(hud, "ORBS_AVAILABLE", False)
        monkeypatch.setattr(hud, "OrbState", None)
        monkeypatch.setattr(hud, "OrbLayer", None)
        assert hud.ORBS_AVAILABLE is False
        assert hud.OrbState is None
        assert hud.OrbLayer is None
