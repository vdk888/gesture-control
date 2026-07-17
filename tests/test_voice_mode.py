"""Tests for VoiceMode -- gesture-triggered voice capture.

Mocks voice.pipeline.VoicePipeline and voice.screenshot.capture_screenshot
so tests run without actual mic/hardware access.
"""

import os
import sys
import time
from unittest.mock import MagicMock, call, patch, mock_open

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modes.base import GestureData

# ---------------------------------------------------------------------------
# Fake landmarks -- reusable across tests
# ---------------------------------------------------------------------------


class FakeLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def _make_landmarks():
    """Return 21 fake landmarks at neutral positions."""
    return [FakeLandmark(0.5, 0.5) for _ in range(21)]


def _make_gesture(name="3 fingers", landmarks=None, fingers_up=None,
                  timestamp=1000.0):
    """Build a GestureData with sensible defaults."""
    if landmarks is None:
        landmarks = _make_landmarks()
    if fingers_up is None:
        fingers_up = [False, True, True, True, False]  # 3 fingers
    return GestureData(
        gesture_name=name,
        fingers_up=fingers_up,
        landmarks=landmarks,
        frame=None,
        width=640,
        height=480,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Mock VoicePipeline
# ---------------------------------------------------------------------------


class MockPipeline:
    """Controllable fake of voice.pipeline.VoicePipeline."""

    def __init__(self, config, on_transcription=None):
        self.config = config
        self.on_transcription = on_transcription
        self._listening = False
        self._start_count = 0
        self._stop_count = 0
        self._stop_result = None  # (audio_path, transcript, duration) or None

    def start(self):
        self._listening = True
        self._start_count += 1

    def stop(self):
        self._listening = False
        self._stop_count += 1
        return self._stop_result

    def is_listening(self):
        return self._listening

    def emit_partial(self, text):
        """Simulate a transcription callback from the pipeline."""
        if self.on_transcription:
            self.on_transcription(text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _patch_voice_module(monkeypatch):
    """Patch the voice module globals so VoicePipeline + screenshot are mocked."""
    monkeypatch.setattr("modes.voice._VoicePipeline", MockPipeline)
    monkeypatch.setattr("modes.voice._capture_screenshot",
                        MagicMock(return_value="/tmp/screenshots/voice_1234.png"))
    monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())


@pytest.fixture
def voice_mode(_patch_voice_module):
    """Create a VoiceMode with default config and no HUD."""
    from modes.voice import VoiceMode
    inject_mock = mock_open()
    config = {
        "voice": {
            "trigger_gesture": "3 fingers",
            "always_on": False,
            "inject_path": "/tmp/test-inject",
            "screenshot_enabled": True,
            "whisper_language": "fr",
            "always_on_toggle_gesture": "Peace",
            "always_on_toggle_hold_s": 1.0,
        }
    }
    with patch("builtins.open", inject_mock):
        mode = VoiceMode(config)
        mode._inject_mock = inject_mock  # attach for test inspection
    mode.enter()
    return mode


@pytest.fixture
def voice_mode_always_on(_patch_voice_module):
    """Create a VoiceMode with always_on=True."""
    from modes.voice import VoiceMode
    inject_mock = mock_open()
    config = {
        "voice": {
            "trigger_gesture": "3 fingers",
            "always_on": True,
            "inject_path": "/tmp/test-inject",
            "screenshot_enabled": True,
            "whisper_language": "fr",
            "always_on_toggle_gesture": "Peace",
            "always_on_toggle_hold_s": 1.0,
        }
    }
    with patch("builtins.open", inject_mock):
        mode = VoiceMode(config)
        mode._inject_mock = inject_mock
    mode.enter()
    return mode


# ---------------------------------------------------------------------------
# Tests: class properties
# ---------------------------------------------------------------------------


class TestVoiceModeProperties:
    def test_name(self, voice_mode):
        assert voice_mode.name == "Voice"

    def test_is_mode_subclass(self, voice_mode):
        from modes.base import Mode
        assert isinstance(voice_mode, Mode)

    def test_inactive_before_enter(self, _patch_voice_module):
        from modes.voice import VoiceMode
        config = {"voice": {}}
        mode = VoiceMode(config)
        assert mode._active is False
        assert mode._pipeline is None


# ---------------------------------------------------------------------------
# Tests: enter / exit lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_enter_creates_pipeline(self, voice_mode):
        assert voice_mode._pipeline is not None
        assert isinstance(voice_mode._pipeline, MockPipeline)

    def test_enter_does_not_start_when_not_always_on(self, voice_mode):
        assert voice_mode._pipeline._start_count == 0
        assert not voice_mode._pipeline.is_listening()

    def test_enter_starts_when_always_on(self, voice_mode_always_on):
        assert voice_mode_always_on._pipeline._start_count >= 1
        assert voice_mode_always_on._pipeline.is_listening()

    def test_exit_stops_pipeline(self, voice_mode):
        voice_mode._pipeline.start()
        assert voice_mode._pipeline.is_listening()
        pipeline_ref = voice_mode._pipeline  # save before exit clears it
        voice_mode.exit()
        assert pipeline_ref._stop_count == 1
        assert voice_mode._pipeline is None

    def test_exit_idempotent_when_pipeline_none(self, voice_mode):
        voice_mode._pipeline = None
        voice_mode.exit()  # should not raise

    def test_enter_resets_state(self, voice_mode):
        voice_mode._was_listening = True
        voice_mode._last_partial = "old text"
        voice_mode._last_cooldown = 999.0
        old_pipeline = voice_mode._pipeline
        voice_mode.enter()
        assert not voice_mode._was_listening
        assert voice_mode._last_partial == ""
        assert voice_mode._last_cooldown == 0.0
        assert voice_mode._pipeline is not old_pipeline  # new pipeline instance


# ---------------------------------------------------------------------------
# Tests: trigger gesture detection
# ---------------------------------------------------------------------------


class TestTriggerDetection:
    def test_three_fingers_is_trigger(self, voice_mode):
        g = _make_gesture("3 fingers")
        assert voice_mode._is_trigger(g, voice_mode.config["voice"])

    def test_pointing_is_not_trigger(self, voice_mode):
        g = _make_gesture("Pointing")
        assert not voice_mode._is_trigger(g, voice_mode.config["voice"])

    def test_fist_is_not_trigger(self, voice_mode):
        g = _make_gesture("Fist")
        assert not voice_mode._is_trigger(g, voice_mode.config["voice"])

    def test_ok_sign_trigger_calls_detect_ok_sign(self, monkeypatch, voice_mode):
        """When trigger_gesture is 'ok_sign', detect_ok_sign is called."""
        voice_mode.config["voice"]["trigger_gesture"] = "ok_sign"

        # Patch the function where it's imported from: hand_tracking
        mock_detect = MagicMock(return_value=True)
        monkeypatch.setattr("hand_tracking.detect_ok_sign", mock_detect)

        g = _make_gesture("Open palm")  # name doesn't matter for ok_sign
        assert voice_mode._is_trigger(g, voice_mode.config["voice"])
        mock_detect.assert_called_once()

    def test_ok_sign_not_detected(self, monkeypatch, voice_mode):
        """When detect_ok_sign returns False, trigger is not active."""
        voice_mode.config["voice"]["trigger_gesture"] = "ok_sign"
        monkeypatch.setattr("hand_tracking.detect_ok_sign",
                            MagicMock(return_value=False))
        g = _make_gesture("Open palm")
        assert not voice_mode._is_trigger(g, voice_mode.config["voice"])

    def test_no_landmarks_not_trigger(self, voice_mode):
        g = GestureData(
            gesture_name="3 fingers", fingers_up=[False, True, True, True, False],
            landmarks=None, frame=None, width=640, height=480, timestamp=1000.0,
        )
        assert not voice_mode._is_trigger(g, voice_mode.config["voice"])


# ---------------------------------------------------------------------------
# Tests: gesture held + not listening → start recording
# ---------------------------------------------------------------------------


class TestGestureStart:
    def test_trigger_starts_pipeline(self, voice_mode):
        g = _make_gesture("3 fingers", timestamp=1000.0)
        assert not voice_mode._pipeline.is_listening()

        result = voice_mode.update(g)
        assert voice_mode._pipeline.is_listening()
        assert voice_mode._pipeline._start_count == 1
        assert "Listening" in result["text"]

    def test_trigger_hud_shows_listening(self, voice_mode):
        g = _make_gesture("3 fingers")
        result = voice_mode.update(g)
        assert "🎤 Listening..." in result["text"]

    def test_no_landmarks_returns_none(self, voice_mode):
        g = GestureData(
            gesture_name="3 fingers", fingers_up=[False, True, True, True, False],
            landmarks=None, frame=None, width=640, height=480, timestamp=1000.0,
        )
        result = voice_mode.update(g)
        assert result is None

    def test_pipeline_none_returns_none(self, _patch_voice_module):
        """When pipeline hasn't been created, update returns None."""
        from modes.voice import VoiceMode
        mode = VoiceMode({"voice": {}})
        mode._pipeline = None
        g = _make_gesture("3 fingers")
        result = mode.update(g)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: gesture held + already listening → show partials
# ---------------------------------------------------------------------------


class TestGestureHeld:
    def test_shows_partial_when_listening(self, voice_mode):
        # First frame: start listening
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)

        # Pipeline emits a partial
        voice_mode._pipeline.emit_partial("Bonjour, je")

        # Next frame: still holding gesture → show partial
        g2 = _make_gesture("3 fingers", timestamp=1000.1)
        result = voice_mode.update(g2)
        assert result["text"] == "Bonjour, je"

    def test_shows_listening_before_partial(self, voice_mode):
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)

        g2 = _make_gesture("3 fingers", timestamp=1000.1)
        result = voice_mode.update(g2)
        assert "🎤 Listening..." in result["text"]


# ---------------------------------------------------------------------------
# Tests: gesture released → stop, screenshot, inject
# ---------------------------------------------------------------------------


class TestGestureRelease:
    def test_release_stops_pipeline(self, voice_mode):
        # Start listening
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)

        # Set stop result
        voice_mode._pipeline._stop_result = (
            "/tmp/audio_1234.wav", "Bonjour le monde", 2.5
        )

        # Release: different gesture (Pointing)
        g2 = _make_gesture("Pointing", timestamp=1000.5)
        result = voice_mode.update(g2)

        assert voice_mode._pipeline._stop_count == 1
        assert not voice_mode._pipeline.is_listening()
        assert "Sent" in result["text"]

    def test_release_captures_screenshot(self, voice_mode):
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)
        voice_mode._pipeline._stop_result = (
            "/tmp/audio.wav", "test", 1.0
        )

        g2 = _make_gesture("Pointing", timestamp=1000.5)
        voice_mode.update(g2)

        # Screenshot mock should have been called
        from modes.voice import _capture_screenshot
        assert _capture_screenshot.called

    def test_release_sends_inject(self, voice_mode):
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)
        voice_mode._pipeline._stop_result = (
            "/tmp/audio.wav", "Bonjour", 1.5
        )

        g2 = _make_gesture("Pointing", timestamp=1000.5)
        result = voice_mode.update(g2)

        # Check result contains "Sent"
        assert "Sent" in result["text"]

    def test_release_no_speech_returns_empty(self, voice_mode):
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)
        voice_mode._pipeline._stop_result = None  # No speech

        g2 = _make_gesture("Pointing", timestamp=1000.5)
        result = voice_mode.update(g2)
        assert result is not None
        assert "Sent" not in result.get("text", "")

    def test_release_screenshot_disabled_skips_capture(self, voice_mode):
        voice_mode.config["voice"]["screenshot_enabled"] = False

        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)
        voice_mode._pipeline._stop_result = ("/tmp/a.wav", "hi", 0.5)

        g2 = _make_gesture("Pointing", timestamp=1000.5)
        result = voice_mode.update(g2)
        assert "Sent" in result["text"]

    def test_release_in_always_on_restarts_pipeline(self, voice_mode):
        """In always-on mode, gesture release injects then restarts pipeline."""
        voice_mode._always_on = True
        voice_mode._pipeline.start()  # pipeline already running

        # Trigger gesture held → starts the trigger-listening state
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)
        assert voice_mode._was_listening

        voice_mode._pipeline._stop_result = ("/tmp/a.wav", "hi", 0.5)

        # Gesture released (non-trigger)
        g2 = _make_gesture("Pointing", timestamp=1000.5)
        result = voice_mode.update(g2)

        # Pipeline should have been stopped then restarted
        assert voice_mode._pipeline._start_count >= 2  # initial + restart
        assert voice_mode._pipeline.is_listening()
        assert "Sent" in result["text"]


# ---------------------------------------------------------------------------
# Tests: cooldown
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_300ms_cooldown_blocks_retrigger(self, voice_mode):
        # First trigger at t=1000.0
        g = _make_gesture("3 fingers", timestamp=1000.0)
        voice_mode.update(g)
        assert voice_mode._pipeline.is_listening()

        # Release
        g2 = _make_gesture("Pointing", timestamp=1000.1)
        voice_mode._pipeline._stop_result = ("/tmp/a.wav", "test", 1.0)
        voice_mode.update(g2)
        first_stop_count = voice_mode._pipeline._stop_count

        # Pipeline is now stopped. Re-trigger at t=1000.2 (within 300ms cooldown)
        # The cooldown was set on release to 1000.1, so 1000.2 - 1000.1 = 0.1s < 0.3s
        g3 = _make_gesture("3 fingers", timestamp=1000.2)
        result = voice_mode.update(g3)
        # Should show partial/placeholder but NOT start because in cooldown
        assert "Listening" in result["text"]
        # Pipeline should NOT have been re-started
        assert voice_mode._pipeline._start_count == 1  # unchanged from first trigger

    def test_after_cooldown_allows_new_trigger(self, monkeypatch):
        """After 300ms+ the trigger gesture fires again."""
        from modes.voice import VoiceMode

        # Control time
        fake_time = [1000.0]

        def mock_monotonic():
            return fake_time[0]

        monkeypatch.setattr("modes.voice._VoicePipeline", MockPipeline)
        monkeypatch.setattr("modes.voice._capture_screenshot",
                            MagicMock(return_value="/tmp/s.png"))
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())
        inject_mock = mock_open()
        monkeypatch.setattr("builtins.open", inject_mock)
        monkeypatch.setattr("modes.voice.time.monotonic", mock_monotonic)

        config = {"voice": {"trigger_gesture": "3 fingers",
                            "inject_path": "/tmp/test-inject",
                            "screenshot_enabled": True,
                            "whisper_language": "fr",
                            "always_on": False,
                            "always_on_toggle_gesture": "Peace",
                            "always_on_toggle_hold_s": 1.0}}
        mode = VoiceMode(config)
        mode.enter()

        # First trigger
        fake_time[0] = 1000.0
        g = _make_gesture("3 fingers", timestamp=1000.0)
        mode.update(g)
        assert mode._pipeline._start_count == 1

        # Release at 1000.1
        mode._pipeline._stop_result = ("/tmp/a.wav", "test", 1.0)
        fake_time[0] = 1000.1
        g2 = _make_gesture("Pointing", timestamp=1000.1)
        mode.update(g2)

        # Advance past cooldown (300ms)
        fake_time[0] = 1000.6
        g3 = _make_gesture("3 fingers", timestamp=1000.6)
        mode.update(g3)
        assert mode._pipeline._start_count == 2  # New start fired


# ---------------------------------------------------------------------------
# Tests: always-on toggle
# ---------------------------------------------------------------------------


class TestAlwaysOnToggle:
    def test_peace_hold_toggles_always_on(self, monkeypatch):
        """Holding Peace sign for >= 1.0s toggles always-on."""
        from modes.voice import VoiceMode

        fake_time = [1000.0]

        class TimeController:
            @staticmethod
            def monotonic():
                return fake_time[0]

        monkeypatch.setattr("modes.voice._VoicePipeline", MockPipeline)
        monkeypatch.setattr("modes.voice._capture_screenshot",
                            MagicMock(return_value="/tmp/s.png"))
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())
        monkeypatch.setattr("builtins.open", mock_open())
        monkeypatch.setattr("modes.voice.time.monotonic", TimeController.monotonic)

        config = {"voice": {"trigger_gesture": "3 fingers",
                            "inject_path": "/tmp/test-inject",
                            "always_on": False,
                            "always_on_toggle_gesture": "Peace",
                            "always_on_toggle_hold_s": 1.0,
                            "screenshot_enabled": True,
                            "whisper_language": "fr"}}
        mode = VoiceMode(config)
        mode.enter()
        assert not mode._always_on

        # Peace sign at t=1000.0 (start hold)
        fake_time[0] = 1000.0
        g = _make_gesture("Peace", timestamp=1000.0)
        mode.update(g)
        assert mode._toggle_hold_start == 1000.0
        # Not held long enough, no toggle yet
        assert not mode._always_on

        # Still holding at t=1001.0 (>= 1.0s) → toggle fires
        fake_time[0] = 1001.0
        g2 = _make_gesture("Peace", timestamp=1001.0)
        result = mode.update(g2)
        assert mode._always_on
        assert result is not None and "Voice always-on: ON" == result["text"]
        assert mode._toggle_hold_start is None  # reset after toggle

    def test_peace_released_before_threshold_no_toggle(self, monkeypatch):
        from modes.voice import VoiceMode

        fake_time = [1000.0]

        class TimeController:
            @staticmethod
            def monotonic():
                return fake_time[0]

        monkeypatch.setattr("modes.voice._VoicePipeline", MockPipeline)
        monkeypatch.setattr("modes.voice._capture_screenshot",
                            MagicMock(return_value="/tmp/s.png"))
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())
        monkeypatch.setattr("builtins.open", mock_open())
        monkeypatch.setattr("modes.voice.time.monotonic", TimeController.monotonic)

        config = {"voice": {"trigger_gesture": "3 fingers",
                            "inject_path": "/tmp/test-inject",
                            "always_on": False,
                            "always_on_toggle_gesture": "Peace",
                            "always_on_toggle_hold_s": 1.0,
                            "screenshot_enabled": True,
                            "whisper_language": "fr"}}
        mode = VoiceMode(config)
        mode.enter()

        # Peace for only 0.5s
        fake_time[0] = 1000.0
        g = _make_gesture("Peace", timestamp=1000.0)
        mode.update(g)

        # Different gesture before threshold
        fake_time[0] = 1000.5
        g2 = _make_gesture("Pointing", timestamp=1000.5)
        mode.update(g2)
        assert not mode._always_on
        assert mode._toggle_hold_start is None  # reset

    def test_toggle_turns_off(self, monkeypatch):
        from modes.voice import VoiceMode

        fake_time = [1000.0]

        class TimeController:
            @staticmethod
            def monotonic():
                return fake_time[0]

        monkeypatch.setattr("modes.voice._VoicePipeline", MockPipeline)
        monkeypatch.setattr("modes.voice._capture_screenshot",
                            MagicMock(return_value="/tmp/s.png"))
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())
        monkeypatch.setattr("builtins.open", mock_open())
        monkeypatch.setattr("modes.voice.time.monotonic", TimeController.monotonic)

        config = {"voice": {"trigger_gesture": "3 fingers",
                            "inject_path": "/tmp/test-inject",
                            "always_on": False,
                            "always_on_toggle_gesture": "Peace",
                            "always_on_toggle_hold_s": 1.0,
                            "screenshot_enabled": True,
                            "whisper_language": "fr"}}
        mode = VoiceMode(config)
        mode.enter()

        # First toggle: OFF → ON
        fake_time[0] = 1000.0
        mode.update(_make_gesture("Peace", timestamp=1000.0))
        fake_time[0] = 1001.0
        result = mode.update(_make_gesture("Peace", timestamp=1001.0))
        assert mode._always_on
        assert "ON" in result["text"]

        # Second toggle: ON → OFF
        fake_time[0] = 1002.0
        mode.update(_make_gesture("Peace", timestamp=1002.0))
        fake_time[0] = 1003.0
        result = mode.update(_make_gesture("Peace", timestamp=1003.0))
        assert not mode._always_on
        assert "OFF" in result["text"]


# ---------------------------------------------------------------------------
# Tests: always-on mode behavior
# ---------------------------------------------------------------------------


class TestAlwaysOnBehavior:
    def test_always_on_shows_partials_without_gesture(self, voice_mode_always_on):
        pipeline = voice_mode_always_on._pipeline
        pipeline.emit_partial("Test transcription en cours")

        g = _make_gesture("Pointing", timestamp=1000.0)
        result = voice_mode_always_on.update(g)
        assert result is not None
        assert "Test transcription en cours" in result["text"]

    def test_always_on_shows_placeholder_before_partial(self, voice_mode_always_on):
        g = _make_gesture("Open palm", timestamp=1000.0)
        result = voice_mode_always_on.update(g)
        assert result is not None
        assert "Voice always-on" in result.get("text", "")


# ---------------------------------------------------------------------------
# Tests: pipeline unavailable → graceful degradation
# ---------------------------------------------------------------------------


class TestPipelineUnavailable:
    def test_enter_no_pipeline_is_noop(self, monkeypatch):
        from modes.voice import VoiceMode
        # Simulate import failure
        monkeypatch.setattr("modes.voice._VoicePipeline", False)
        monkeypatch.setattr("modes.voice._capture_screenshot", False)
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())
        monkeypatch.setattr("builtins.open", mock_open())

        config = {"voice": {}}
        mode = VoiceMode(config)
        mode.enter()
        assert mode._pipeline is None

    def test_update_with_no_pipeline_returns_none(self, monkeypatch):
        from modes.voice import VoiceMode
        monkeypatch.setattr("modes.voice._VoicePipeline", False)
        monkeypatch.setattr("modes.voice._capture_screenshot", False)
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())
        monkeypatch.setattr("builtins.open", mock_open())

        config = {"voice": {}}
        mode = VoiceMode(config)
        mode.enter()
        g = _make_gesture("3 fingers")
        result = mode.update(g)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: transcription callback
# ---------------------------------------------------------------------------


class TestTranscriptionCallback:
    def test_callback_updates_last_partial(self, voice_mode):
        voice_mode._pipeline.emit_partial("Salut le monde")
        assert voice_mode._last_partial == "Salut le monde"

    def test_callback_overwrites_previous(self, voice_mode):
        voice_mode._pipeline.emit_partial("premier")
        assert voice_mode._last_partial == "premier"
        voice_mode._pipeline.emit_partial("deuxieme plus long")
        assert voice_mode._last_partial == "deuxieme plus long"


# ---------------------------------------------------------------------------
# Tests: inject format
# ---------------------------------------------------------------------------


class TestInjectFormat:
    def test_inject_writes_structured_block(self, _patch_voice_module):
        """Verify the inject block contains required format elements."""
        from modes.voice import VoiceMode
        inject_mock = mock_open()
        config = {"voice": {
            "trigger_gesture": "3 fingers",
            "inject_path": "/tmp/test-inject",
            "whisper_language": "fr",
            "screenshot_enabled": True,
            "always_on": False,
            "always_on_toggle_gesture": "Peace",
            "always_on_toggle_hold_s": 1.0,
        }}
        with patch("builtins.open", inject_mock):
            mode = VoiceMode(config)
            mode.enter()

            ok = mode._inject(
                audio_path="/tmp/audio.wav",
                transcript="Bonjour le monde",
                duration=3.2,
                screenshot_path="/tmp/screenshot.png",
                voice_cfg=mode.config["voice"],
            )
            assert ok

            # Gather all writes to the inject file
            handle = inject_mock()
            all_writes = "".join(
                ca[0][0] if ca[0] else ""
                for ca in handle.write.call_args_list
            )
            assert "VOICE_GESTURE" in all_writes
            assert "authorized=yes" in all_writes
            assert "path=/tmp/audio.wav" in all_writes
            assert "screenshot=/tmp/screenshot.png" in all_writes
            assert "duration=3.2s" in all_writes
            assert "lang=fr" in all_writes
            assert "transcript=Bonjour le monde" in all_writes
            assert "Voice message from Joris via GestureControl" in all_writes
            assert "low-risk=auto" in all_writes
            assert "Reply in French" in all_writes

    def test_inject_no_screenshot_uses_none_placeholder(self, _patch_voice_module):
        """Empty screenshot path becomes '(none)' in the inject block."""
        from modes.voice import VoiceMode
        inject_mock = mock_open()
        config = {"voice": {
            "trigger_gesture": "3 fingers",
            "inject_path": "/tmp/test-inject",
            "whisper_language": "fr",
            "always_on": False,
            "always_on_toggle_gesture": "Peace",
            "always_on_toggle_hold_s": 1.0,
        }}
        with patch("builtins.open", inject_mock):
            mode = VoiceMode(config)
            mode.enter()

            ok = mode._inject(
                audio_path="/tmp/a.wav",
                transcript="test",
                duration=1.0,
                screenshot_path="",
                voice_cfg=mode.config["voice"],
            )
            assert ok
            handle = inject_mock()
            all_writes = "".join(
                ca[0][0] if ca[0] else ""
                for ca in handle.write.call_args_list
            )
            assert "screenshot=(none)" in all_writes
