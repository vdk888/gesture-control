"""VoiceMode — always-on background voice with HUD transcription streaming.

The voice pipeline runs continuously once the app starts: mic -> VAD -> whisper
-> HUD streaming.  The 3-finger gesture (handled by the main loop) triggers a
"send now": flushes the last 15 s of audio, captures a screenshot, and injects
everything to the agent.

VoiceMode is NOT entered/exited for each interaction — it is a persistent
background service.  enter() starts it once; exit() tears it down on app quit.
"""

import logging
import os
import time

from modes.base import Mode, GestureData

logger = logging.getLogger(__name__)

_VoicePipeline = None
_capture_screenshot = None


def _ensure_voice_imports():
    global _VoicePipeline, _capture_screenshot
    if _VoicePipeline is None:
        try:
            from voice.pipeline import VoicePipeline as VP
            _VoicePipeline = VP
        except ImportError:
            _VoicePipeline = False
    if _capture_screenshot is None:
        try:
            from voice.screenshot import capture_screenshot as cs
            _capture_screenshot = cs
        except ImportError:
            _capture_screenshot = False


class VoiceMode(Mode):
    name = "Voice"

    def __init__(self, config: dict, hud=None):
        super().__init__(config, hud)
        self._pipeline = None
        self._always_on = True       # always listening by default
        self._last_partial = ""
        self._cooldown_until = 0.0

        # Orb state
        self.listening = False
        self.processing = False
        self.speaking = False
        self.error = None

    # -- lifecycle -----------------------------------------------------------

    def enter(self):
        """Start the voice pipeline (called once at app start or config toggle)."""
        super().enter()
        if self._pipeline is not None:
            return  # already running

        voice_cfg = self.config.get("voice", {})
        self._always_on = voice_cfg.get("always_on", True)
        self._last_partial = ""

        _ensure_voice_imports()
        if _VoicePipeline and _VoicePipeline is not False:
            try:
                self._pipeline = _VoicePipeline(
                    config=self.config,
                    on_transcription=self._on_transcription,
                    always_on=True,           # continuous VAD
                    rolling_buffer_s=15,      # keep last 15 s
                )
                self._pipeline.start()
                logger.info("Voice pipeline started (always-on)")
                self.listening = True
            except Exception as exc:
                logger.error(f"Voice pipeline init failed: {exc}")
                self.error = str(exc)
                self._pipeline = None
        else:
            logger.warning("Voice pipeline module not available; voice mode disabled")
            self.error = "Voice pipeline not available"
            self._pipeline = None

    def exit(self):
        """Stop the pipeline (called at app quit)."""
        super().exit()
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:
                pass
            self._pipeline = None
        self.listening = False
        self.processing = False
        self.speaking = False

    # -- per-frame (called by main loop even when voice is not "active") ----

    def update(self, gesture: GestureData):
        """Stream HUD transcription.  Gesture-triggered send is handled
        by trigger_send(), not here."""

        # Keep HUD showing latest partial
        if self._last_partial:
            return {"text": self._last_partial, "level": None}

        status = "🎤 listening..." if self.listening else "🎤 paused"
        return {"text": status, "level": None}

    # -- public API used by main loop ---------------------------------------

    def trigger_send(self) -> bool:
        """Flush last 15 s of audio + screenshot -> inject to agent.

        Returns True if something was sent, False if pipeline isn't ready
        or cooldown is active.
        """
        now = time.monotonic()
        if now < self._cooldown_until:
            return False
        if self._pipeline is None:
            return False

        self.processing = True
        self.speaking = False
        try:
            # Flush the rolling buffer
            result = self._pipeline.flush()
            if result is None:
                self.processing = False
                return False

            audio_path, transcript, duration_s = result

            # Screenshot
            screenshot_path = "(none)"
            if (self.config.get("voice", {}).get("screenshot_enabled", True)
                    and _capture_screenshot is not False):
                try:
                    screenshot_path = _capture_screenshot()
                except Exception:
                    pass

            # Inject
            self._pipeline.inject(
                transcript=transcript,
                audio_path=audio_path,
                screenshot_path=screenshot_path,
                duration_s=duration_s,
            )

            self._cooldown_until = now + 2.0  # 2 s cooldown
            self.speaking = True
            self._last_partial = ""
            if self.hud:
                self.hud.show(text=f"Sent ✅ ({duration_s:.0f}s)", level=100)
            logger.info(f"Voice sent: {duration_s:.1f}s, {len(transcript)} chars")
        except Exception as exc:
            logger.error(f"Voice send failed: {exc}")
            self.error = str(exc)
        finally:
            self.processing = False

        return True

    def toggle_always_on(self) -> bool:
        """Toggle continuous listening on/off. Returns new state."""
        self._always_on = not self._always_on
        if self._pipeline is not None:
            if self._always_on:
                self._pipeline.resume()
            else:
                self._pipeline.pause()
        self.listening = self._always_on
        status = "ON" if self._always_on else "OFF"
        if self.hud:
            self.hud.show(text=f"Voice always-on: {status}", level=100 if self._always_on else 0)
        logger.info(f"Voice always-on toggled: {status}")
        return self._always_on

    # -- internal -----------------------------------------------------------

    def _on_transcription(self, partial_text: str):
        """Callback from VoicePipeline — receives streaming partials."""
        self._last_partial = partial_text
        if self.hud and partial_text:
            self.hud.show_transcription(partial_text)
