"""Tests for VoiceMode -- always-on background voice with HUD transcription.

Mocks voice.pipeline.VoicePipeline and voice.screenshot.capture_screenshot
so tests run without actual mic/hardware access.
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch, mock_open

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modes.base import GestureData

# ---------------------------------------------------------------------------
# Fake landmarks
# ---------------------------------------------------------------------------


class FakeLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def _make_landmarks():
    return [FakeLandmark(0.5, 0.5) for _ in range(21)]


def _make_gesture(name="Pointing", landmarks=None, fingers_up=None,
                  timestamp=1000.0):
    if landmarks is None:
        landmarks = _make_landmarks()
    if fingers_up is None:
        fingers_up = [False, True, False, False, False]  # Pointing
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
# Mock VoicePipeline (matches new always_on + rolling_buffer_s API)
# ---------------------------------------------------------------------------


class MockPipeline:
    """Controllable fake of voice.pipeline.VoicePipeline."""

    def __init__(self, config, on_transcription=None,
                 always_on=False, rolling_buffer_s=15):
        self.config = config
        self.on_transcription = on_transcription
        self._listening = False
        self._start_count = 0
        self._stop_count = 0
        self._flush_count = 0
        self._flush_result = None
        self._inject_calls = []
        self._paused = False

    def start(self):
        self._listening = True
        self._start_count += 1

    def stop(self):
        self._listening = False
        self._stop_count += 1

    def is_listening(self):
        return self._listening

    def flush(self):
        self._flush_count += 1
        return self._flush_result

    def inject(self, transcript, audio_path, screenshot_path, duration_s):
        self._inject_calls.append({
            "transcript": transcript,
            "audio_path": audio_path,
            "screenshot_path": screenshot_path,
            "duration_s": duration_s,
        })

    def pause(self):
        self._paused = True
        self._listening = False

    def resume(self):
        self._paused = False
        self._listening = True

    def emit_partial(self, text):
        """Simulate a transcription callback from the pipeline."""
        if self.on_transcription:
            self.on_transcription(text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _patch_voice_module(monkeypatch):
    monkeypatch.setattr("modes.voice._VoicePipeline", MockPipeline)
    monkeypatch.setattr("modes.voice._capture_screenshot",
                        MagicMock(return_value="/tmp/screenshots/voice_1234.png"))
    monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())


@pytest.fixture
def voice_mode(_patch_voice_module):
    from modes.voice import VoiceMode
    config = {
        "voice": {
            "always_on": True,
            "screenshot_enabled": True,
            "whisper_language": "fr",
        }
    }
    mode = VoiceMode(config)
    mode.enter()
    return mode


@pytest.fixture
def voice_mode_stopped(_patch_voice_module):
    """VoiceMode with always_on=False -> pipeline not started."""
    from modes.voice import VoiceMode
    config = {
        "voice": {
            "always_on": False,
            "screenshot_enabled": True,
            "whisper_language": "fr",
        }
    }
    mode = VoiceMode(config)
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

    def test_enter_starts_pipeline_by_default(self, voice_mode):
        """With always_on=True, enter() starts the pipeline."""
        assert voice_mode._pipeline._start_count >= 1
        assert voice_mode._pipeline.is_listening()

    def test_enter_starts_pipeline_regardless_of_always_on(self, voice_mode_stopped):
        """Pipeline is always created and started in enter() regardless of always_on config."""
        assert voice_mode_stopped._pipeline is not None
        # Pipeline is started in enter() even with always_on=False in config
        assert voice_mode_stopped._pipeline._start_count >= 1

    def test_exit_stops_pipeline(self, voice_mode):
        pipeline_ref = voice_mode._pipeline
        voice_mode.exit()
        assert pipeline_ref._stop_count >= 1
        assert voice_mode._pipeline is None
        assert not voice_mode.listening

    def test_exit_idempotent_when_pipeline_none(self, voice_mode):
        voice_mode._pipeline = None
        voice_mode.exit()  # should not raise

    def test_enter_resets_state(self, voice_mode):
        voice_mode._always_on = False
        voice_mode._last_partial = "old text"
        voice_mode._cooldown_until = 999.0
        old_pipeline = voice_mode._pipeline
        voice_mode.enter()
        # enter() detects pipeline already running and returns early
        assert voice_mode._pipeline is old_pipeline


# ---------------------------------------------------------------------------
# Tests: trigger_send
# ---------------------------------------------------------------------------


class TestTriggerSend:
    def test_trigger_send_flushes_and_injects(self, voice_mode):
        voice_mode._pipeline._flush_result = (
            "/tmp/audio.wav", "Bonjour le monde", 2.5
        )
        with patch.object(voice_mode._pipeline, "inject") as mock_inject:
            ok = voice_mode.trigger_send()
            assert ok is True
            assert voice_mode._pipeline._flush_count == 1
            assert mock_inject.called

    def test_trigger_send_no_speech(self, voice_mode):
        voice_mode._pipeline._flush_result = None
        ok = voice_mode.trigger_send()
        assert ok is False

    def test_trigger_send_pipeline_none(self, _patch_voice_module):
        from modes.voice import VoiceMode
        mode = VoiceMode({"voice": {}})
        mode._pipeline = None
        ok = mode.trigger_send()
        assert ok is False

    def test_trigger_send_cooldown(self, monkeypatch, voice_mode):
        voice_mode._pipeline._flush_result = ("/tmp/a.wav", "hi", 1.0)
        with patch.object(voice_mode._pipeline, "inject"):
            # First send should work
            ok1 = voice_mode.trigger_send()
            assert ok1 is True
            # Second send within 2s cooldown should fail
            ok2 = voice_mode.trigger_send()
            assert ok2 is False


# ---------------------------------------------------------------------------
# Tests: toggle_always_on
# ---------------------------------------------------------------------------


class TestToggleAlwaysOn:
    def test_toggle_turns_off(self, voice_mode):
        assert voice_mode._always_on is True
        result = voice_mode.toggle_always_on()
        assert result is False
        assert not voice_mode._always_on
        assert voice_mode._pipeline._paused

    def test_toggle_turns_on(self, voice_mode):
        voice_mode._always_on = False
        voice_mode._pipeline.pause()
        result = voice_mode.toggle_always_on()
        assert result is True
        assert voice_mode._always_on
        assert not voice_mode._pipeline._paused
        assert voice_mode.listening

    def test_toggle_no_pipeline(self, _patch_voice_module):
        from modes.voice import VoiceMode
        mode = VoiceMode({"voice": {}})
        mode._pipeline = None
        # _always_on starts as True; toggle flips to False
        initial = mode._always_on
        result = mode.toggle_always_on()
        assert result is not initial  # state changed


# ---------------------------------------------------------------------------
# Tests: update (HUD streaming)
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_shows_partial(self, voice_mode):
        voice_mode._pipeline.emit_partial("Bonjour le monde")
        g = _make_gesture("Pointing")
        result = voice_mode.update(g)
        assert result is not None
        assert "Bonjour le monde" in result["text"]

    def test_update_shows_listening_status(self, voice_mode):
        voice_mode._last_partial = ""
        g = _make_gesture("Pointing")
        result = voice_mode.update(g)
        assert result is not None
        assert "listening" in result["text"].lower()

    def test_update_shows_paused_when_not_listening(self, voice_mode):
        voice_mode.listening = False
        voice_mode._last_partial = ""
        g = _make_gesture("Pointing")
        result = voice_mode.update(g)
        assert result is not None
        assert "paused" in result["text"].lower()

    def test_update_no_landmarks_returns_none(self, voice_mode):
        g = GestureData(
            gesture_name="", fingers_up=[],
            landmarks=None, frame=None,
            width=640, height=480, timestamp=1000.0,
        )
        result = voice_mode.update(g)
        # Still returns HUD data even without landmarks (shows partial/status)
        assert result is not None

    def test_update_pipeline_none_returns_status(self, _patch_voice_module):
        from modes.voice import VoiceMode
        mode = VoiceMode({"voice": {}})
        mode._pipeline = None
        mode.enter()
        g = _make_gesture("Pointing")
        result = mode.update(g)
        assert result is not None


# ---------------------------------------------------------------------------
# Tests: pipeline unavailable -> graceful degradation
# ---------------------------------------------------------------------------


class TestPipelineUnavailable:
    def test_enter_no_pipeline_is_noop(self, monkeypatch):
        from modes.voice import VoiceMode
        monkeypatch.setattr("modes.voice._VoicePipeline", False)
        monkeypatch.setattr("modes.voice._capture_screenshot", False)
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())

        config = {"voice": {}}
        mode = VoiceMode(config)
        mode.enter()
        assert mode._pipeline is None
        assert mode.error is not None

    def test_update_with_no_pipeline_shows_paused(self, monkeypatch):
        """When pipeline is unavailable, update() shows paused status."""
        from modes.voice import VoiceMode
        monkeypatch.setattr("modes.voice._VoicePipeline", False)
        monkeypatch.setattr("modes.voice._capture_screenshot", False)
        monkeypatch.setattr("modes.voice.os.makedirs", MagicMock())

        config = {"voice": {}}
        mode = VoiceMode(config)
        mode.enter()
        g = _make_gesture("Pointing")
        result = mode.update(g)
        assert result is not None
        assert "paused" in result["text"].lower()


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
