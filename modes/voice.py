"""VoiceMode -- gesture-triggered voice capture with whisper transcription.

Trigger gesture (default "3 fingers") replaces the wake word: make the gesture,
speak, release to send. Captures a screenshot on every utterance. Injects
transcript + screenshot path into the DeepSeek channel.

Always-on toggle (Peace sign held 1s) keeps the mic VAD-gated continuously.
"""

import logging
import os
import time

from modes.base import Mode, GestureData

logger = logging.getLogger(__name__)

# Lazy imports -- voice pipeline and screenshot are built concurrently.
# Import errors are caught in enter() so the mode gracefully degrades.
_VoicePipeline = None
_capture_screenshot = None


def _ensure_voice_imports():
    """Lazy-load voice.pipeline and voice.screenshot on first use."""
    global _VoicePipeline, _capture_screenshot
    if _VoicePipeline is None:
        try:
            from voice.pipeline import VoicePipeline as VP
            _VoicePipeline = VP
        except ImportError:
            _VoicePipeline = False  # Sentinel: import failed, don't retry
    if _capture_screenshot is None:
        try:
            from voice.screenshot import capture_screenshot as cs
            _capture_screenshot = cs
        except ImportError:
            _capture_screenshot = False


class VoiceMode(Mode):
    name = "Voice"

    # -- construction --------------------------------------------------

    def __init__(self, config: dict, hud=None):
        super().__init__(config, hud)
        self._pipeline = None          # VoicePipeline instance (or None)
        self._was_listening = False     # gesture-held state machine flag
        self._last_cooldown = 0.0      # monotonic seconds of last trigger
        self._always_on = False        # runtime toggle (overrides config)
        self._toggle_hold_start = None # float or None while Peace held
        self._last_partial = ""        # latest transcription partial

    # -- lifecycle -----------------------------------------------------

    def enter(self):
        super().enter()
        voice_cfg = self.config.get("voice", {})
        self._always_on = voice_cfg.get("always_on", False)
        self._last_partial = ""
        self._was_listening = False
        self._last_cooldown = 0.0
        self._toggle_hold_start = None

        _ensure_voice_imports()
        if _VoicePipeline and _VoicePipeline is not False:
            try:
                self._pipeline = _VoicePipeline(
                    config=voice_cfg,
                    on_transcription=self._on_partial,
                )
                if self._always_on:
                    self._pipeline.start()
                    logger.info("VoiceMode: always-on pipeline started at enter()")
            except Exception as exc:
                logger.warning("VoiceMode: pipeline init failed: %s", exc)
                self._pipeline = None
        else:
            logger.warning("VoiceMode: voice.pipeline not available, mode is no-op")

    def exit(self):
        super().exit()
        if self._pipeline:
            try:
                self._pipeline.stop()
            except Exception as exc:
                logger.debug("VoiceMode: pipeline.stop() error during exit: %s", exc)
            self._pipeline = None
        self._last_partial = ""
        self._was_listening = False
        self._toggle_hold_start = None

    # -- callback ------------------------------------------------------

    def _on_partial(self, text: str):
        """Called by VoicePipeline ~500ms with latest partial transcription."""
        self._last_partial = text

    # -- per-frame update ----------------------------------------------

    def update(self, gesture: GestureData):
        """Process one frame for voice mode.

        Returns a HUD dict with at least a 'text' key, or None if the HUD
        should show nothing.
        """
        if self._pipeline is None:
            return None

        # No hand in frame -- nothing to act on
        if gesture.landmarks is None:
            return None

        now = time.monotonic()
        voice_cfg = self.config.get("voice", {})

        # --- always-on toggle (Peace sign held) ---
        toggle_gesture = voice_cfg.get("always_on_toggle_gesture", "Peace")
        toggle_hold_s = voice_cfg.get("always_on_toggle_hold_s", 1.0)

        if gesture.gesture_name == toggle_gesture:
            if self._toggle_hold_start is None:
                self._toggle_hold_start = now
            elif now - self._toggle_hold_start >= toggle_hold_s:
                self._always_on = not self._always_on
                self._toggle_hold_start = None
                if self._always_on and not self._pipeline.is_listening():
                    self._pipeline.start()
                elif not self._always_on and self._pipeline.is_listening():
                    self._pipeline.stop()
                status = "ON" if self._always_on else "OFF"
                logger.info("VoiceMode: always-on toggled to %s", status)
                return {"text": f"Voice always-on: {status}"}
        else:
            self._toggle_hold_start = None

        # --- trigger detection ---
        trigger_active = self._is_trigger(gesture, voice_cfg)

        # --- cooldown enforcement ---
        cooldown_s = 0.300
        in_cooldown = (now - self._last_cooldown) < cooldown_s

        listening = self._pipeline.is_listening()

        # --- gesture released, was listening (BEFORE always-on display) ---
        if self._was_listening and not trigger_active:
            self._was_listening = False
            self._last_cooldown = now
            result = self._pipeline.stop()

            if result is None:
                # No speech detected
                return {"text": ""}

            audio_path, transcript, duration = result

            # Capture screenshot
            screenshot_path = ""
            if voice_cfg.get("screenshot_enabled", True):
                _ensure_voice_imports()
                if _capture_screenshot and _capture_screenshot is not False:
                    try:
                        screenshot_path = _capture_screenshot()
                    except Exception as exc:
                        logger.warning("VoiceMode: screenshot failed: %s", exc)

            # Inject to DeepSeek channel
            inject_ok = self._inject(
                audio_path=audio_path,
                transcript=transcript,
                duration=duration,
                screenshot_path=screenshot_path,
                voice_cfg=voice_cfg,
            )

            if self._always_on:
                # Restart pipeline for continuous VAD
                try:
                    self._pipeline.start()
                except Exception as exc:
                    logger.warning("VoiceMode: restart after inject failed: %s", exc)

            return {"text": "Sent ✅" if inject_ok else "Sent ✅ (inject failed)"}

        # --- always-on mode: pipeline runs continuously, show partials ---
        if self._always_on and listening and not trigger_active:
            return {"text": self._last_partial or "Voice always-on"}

        # --- trigger gesture active ---
        if trigger_active:
            if in_cooldown:
                return {"text": self._last_partial or "🎤 Listening..."}

            if not listening:
                # Start recording
                self._pipeline.start()
                self._was_listening = True
                self._last_cooldown = now
                self._last_partial = ""
                return {"text": "🎤 Listening..."}
            else:
                # Already listening (always-on or already started): mark hold
                # so release triggers inject, and show partial transcription
                self._was_listening = True
                return {"text": self._last_partial or "🎤 Listening..."}

        return None

    # -- helpers -------------------------------------------------------

    def _is_trigger(self, gesture: GestureData, voice_cfg: dict) -> bool:
        """Return True if the current gesture matches the configured trigger."""
        if gesture.landmarks is None:
            return False
        trigger = voice_cfg.get("trigger_gesture", "3 fingers")
        if gesture.gesture_name == trigger:
            return True
        if trigger == "ok_sign":
            from hand_tracking import detect_ok_sign
            return detect_ok_sign(gesture.landmarks)
        return False

    def _inject(self, audio_path: str, transcript: str, duration: float,
                 screenshot_path: str, voice_cfg: dict) -> bool:
        """Append VOICE_GESTURE block to the DeepSeek inject file.

        Returns True on success, False if the inject path is not writable.
        """
        inject_path = os.path.expanduser(
            voice_cfg.get("inject_path", "~/.claude/channels/telegram-deepseek/inject")
        )
        lang = voice_cfg.get("whisper_language", "fr")
        ts = int(time.time())
        ss = screenshot_path or "(none)"
        wav = audio_path or "(none)"

        block = (
            f"VOICE_GESTURE ts={ts} authorized=yes path={wav} "
            f"screenshot={ss} duration={duration:.1f}s lang={lang} "
            f"transcript={transcript}\n"
            f"🎙️ Voice message from Joris via GestureControl. "
            f"Screenshot at path. Execute: low-risk=auto. Reply in French.\n"
        )

        try:
            os.makedirs(os.path.dirname(inject_path), exist_ok=True)
            with open(inject_path, "a") as f:
                f.write(block)
            logger.info("VoiceMode: injected to %s", inject_path)
            return True
        except OSError as exc:
            logger.error("VoiceMode: inject failed for %s: %s", inject_path, exc)
            return False
