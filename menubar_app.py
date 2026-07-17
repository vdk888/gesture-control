#!/usr/bin/env python3
"""
GestureControl -- Menu Bar Controller (macOS)

Shows a status icon in the Mac menu bar. Click to see current mode and
toggle HUD, orb, voice features. Manages the gesture control processing
loop in a background thread.

Uses rumps (https://github.com/jaredks/rumps) with PIL-drawn menu bar icons
at 4x supersampling for Retina anti-aliasing.

Design decisions:
- Icon: coloured dots drawn with PIL at 4x, downsampled with LANCZOS.
  Green filled dot = tracking active, grey ring = paused, red filled dot = error.
  The grey ring uses a medium grey visible in both light and dark mode.
- Background thread: the gesture control loop runs without the OpenCV preview
  window (cv2.imshow cannot run on a background thread on macOS). The HUD
  overlay provides all visual feedback.
- State polling: rumps.Timer every 2s reads thread-safe shared state and
  updates the menu. No subprocess polling -- all fast attribute reads.
- rumps: macOS NSStatusBar wrapper. quit_button=None gives us a custom Quit
  that shuts down the gesture loop before exiting.

LaunchAgent: ~/Library/LaunchAgents/com.bubble.gesture-control.plist
"""

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════
# Icon generation (PIL, 4x supersample, LANCZOS downsample)
# ═══════════════════════════════════════════════════════════════════════════

def _make_icon(state: str) -> str:
    """Render a dot/ring glyph for the menu bar using PIL.

    Icon drawn at 4x supersampling then downsampled for crisp Retina
    anti-aliasing. Same technique as the audio-listener menubar.

    States:
      active -> green filled dot   (tracking, hand detected)
      paused -> grey ring          (tracking paused)
      error  -> red filled dot     (error condition)
      off    -> grey ring          (not started)
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""

    SS = 4                       # supersample factor
    size = 22                    # logical px (menu-bar height)
    S = size * SS                # pixel buffer
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy = S // 2, S // 2
    r = 7 * SS                   # dot/ring radius

    if state == "active":
        # Green filled dot -- tracking active
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 190, 0, 255))
    elif state == "error":
        # Red filled dot -- error condition
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(220, 50, 50, 255))
    elif state in ("paused", "off"):
        # Grey ring -- paused or not started
        w = 2 * SS
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                   outline=(140, 140, 140, 255), width=w)

    img = img.resize((size, size), Image.LANCZOS)
    path = os.path.join(tempfile.gettempdir(), f"gc_icon_{state}.png")
    img.save(path, "PNG")
    return path


# ═══════════════════════════════════════════════════════════════════════════
# Shared state (thread-safe bridge between gesture loop and menubar)
# ═══════════════════════════════════════════════════════════════════════════

class _SharedState:
    """Thread-safe state shared between the background gesture loop and the
    main-thread menubar.

    The gesture loop writes state; the timer callback reads it.  Toggle
    commands from the menubar are set as flags the gesture loop consumes
    on its next frame.
    """

    def __init__(self):
        self._lock = threading.Lock()

        # ── status fields (written by gesture loop) ──
        self.running: bool = False
        self.error: Optional[str] = None
        self.mode: str = ""
        self.fps: float = 0.0
        self.hand: str = ""                       # detected gesture name or ""
        self.hud_visible: bool = True
        self.orb_visible: bool = False
        self.voice_always_on: bool = False
        self.voice_muted: bool = False

        # ── toggle commands (set by menubar, consumed by gesture loop) ──
        self._cmd_toggle_hud: bool = False
        self._cmd_toggle_orb: bool = False
        self._cmd_toggle_voice_always_on: bool = False
        self._cmd_toggle_voice_mute: bool = False
        self._cmd_pause: bool = False
        self._cmd_resume: bool = False

    # ── snapshot (for timer callback) ──────────────────────────────────

    def snapshot(self) -> dict:
        """Return a consistent shallow-copy dict of all status fields."""
        with self._lock:
            return {
                "running": self.running,
                "error": self.error,
                "mode": self.mode,
                "fps": self.fps,
                "hand": self.hand,
                "hud_visible": self.hud_visible,
                "orb_visible": self.orb_visible,
                "voice_always_on": self.voice_always_on,
                "voice_muted": self.voice_muted,
            }

    # ── setters (called by gesture loop, one field at a time is fine) ──

    def set_error(self, msg: str):
        with self._lock:
            self.error = msg
            self.running = False

    def set_status(self, mode: str, fps: float, hand: str):
        with self._lock:
            self.running = True
            self.error = None
            self.mode = mode
            self.fps = fps
            self.hand = hand

    # ── toggle commands ────────────────────────────────────────────────

    def request_toggle_hud(self):
        with self._lock:
            self._cmd_toggle_hud = True

    def request_toggle_orb(self):
        with self._lock:
            self._cmd_toggle_orb = True

    def request_toggle_voice_always_on(self):
        with self._lock:
            self._cmd_toggle_voice_always_on = True

    def request_toggle_voice_mute(self):
        with self._lock:
            self._cmd_toggle_voice_mute = True

    def request_pause(self):
        with self._lock:
            self._cmd_pause = True

    def request_resume(self):
        with self._lock:
            self._cmd_resume = True

    # ── consumers (called by gesture loop) ─────────────────────────────

    def consume_toggles(self) -> dict:
        """Atomically read and clear all pending toggle commands."""
        with self._lock:
            cmds = {
                "toggle_hud": self._cmd_toggle_hud,
                "toggle_orb": self._cmd_toggle_orb,
                "toggle_voice_always_on": self._cmd_toggle_voice_always_on,
                "toggle_voice_mute": self._cmd_toggle_voice_mute,
                "pause": self._cmd_pause,
                "resume": self._cmd_resume,
            }
            self._cmd_toggle_hud = False
            self._cmd_toggle_orb = False
            self._cmd_toggle_voice_always_on = False
            self._cmd_toggle_voice_mute = False
            self._cmd_pause = False
            self._cmd_resume = False
            return cmds

    # ── internal helpers ───────────────────────────────────────────────

    def _apply_toggle_hud(self):
        with self._lock:
            self.hud_visible = not self.hud_visible

    def _apply_toggle_orb(self):
        with self._lock:
            self.orb_visible = not self.orb_visible

    def _apply_toggle_voice_always_on(self):
        with self._lock:
            self.voice_always_on = not self.voice_always_on

    def _apply_toggle_voice_mute(self):
        with self._lock:
            self.voice_muted = not self.voice_muted


# ═══════════════════════════════════════════════════════════════════════════
# Gesture controller (runs gesture_control loop in background thread)
# ═══════════════════════════════════════════════════════════════════════════

class GestureController:
    """Encapsulates the gesture control processing loop, adapted for
    background-thread operation (no OpenCV preview window).

    The original main loop from gesture_control.py is preserved here but
    without cv2.imshow / cv2.waitKey -- the HUD overlay provides all
    visual feedback when running under the menubar.
    """

    def __init__(self, state: _SharedState):
        self._state = state
        self._stop_event = threading.Event()
        self._paused_event = threading.Event()
        self._paused_event.set()   # not paused initially (set = run)
        self._thread: Optional[threading.Thread] = None

        # References held for cleanup
        self._cap = None
        self._landmarker = None
        self._hud = None
        self._current_mode = None
        self._modes: dict = {}
        self._mode_order: list = []

    # ── public API ────────────────────────────────────────────────────

    def start(self):
        """Launch the gesture control loop in a daemon background thread."""
        self._stop_event.clear()
        self._paused_event.set()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gesture-control-loop")
        self._thread.start()

    def stop(self, timeout: float = 3.0):
        """Signal the loop to stop and wait for thread exit."""
        self._stop_event.set()
        self._paused_event.set()   # unblock if paused
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── main loop (runs in background thread) ─────────────────────────

    def _run(self):
        """Main gesture control loop. Runs in a background daemon thread."""
        try:
            import cv2
            from hand_tracking import (
                create_landmarker, detect, fingers_up, name_gesture, draw_hand,
            )
            from modes.base import GestureData
            from modes import MODE_REGISTRY
            from config_manager import load_config
            from hud import HUD

            # Optional orb imports
            try:
                from orbs import OrbLayer, OrbState
            except ImportError:
                OrbLayer = None  # type: ignore[assignment]
                OrbState = None  # type: ignore[assignment]
        except Exception as e:
            self._state.set_error(f"Import failed: {e}")
            return

        # ── init camera ────────────────────────────────────────────────
        config = load_config()
        cap = cv2.VideoCapture(config["camera_index"])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["camera_width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["camera_height"])
        if not cap.isOpened():
            self._state.set_error(
                "Camera not available. Check System Settings > "
                "Privacy & Security > Camera."
            )
            return
        self._cap = cap

        # ── init hand tracking ─────────────────────────────────────────
        landmarker = create_landmarker(num_hands=1)
        self._landmarker = landmarker

        # ── init HUD (always created; visibility toggled via show/hide) ──
        hud = HUD()
        self._hud = hud

        # ── init modes ─────────────────────────────────────────────────
        mode_names = config["modes"]
        modes: dict = {}
        voice_mode = None
        for name in mode_names:
            if name in MODE_REGISTRY and MODE_REGISTRY[name] is not None:
                modes[name] = MODE_REGISTRY[name](config, hud)
                if name == "voice":
                    voice_mode = modes[name]

        if not modes:
            self._state.set_error("No valid modes configured. Check config.json.")
            cap.release()
            landmarker.close()
            return
        self._modes = modes
        self._mode_order = list(modes.keys())

        current_idx = 0
        current_mode = modes[self._mode_order[current_idx]]
        current_mode.enter()
        self._current_mode = current_mode

        # ── orb setup ──────────────────────────────────────────────────
        # The HUD manages its own OrbLayer internally via show_orb()/hide_orb().
        # We just track whether the import succeeded so we can call
        # hud.set_orb_state() on each frame.
        _orb_available = OrbLayer is not None and OrbState is not None

        # ── mode-switching state ───────────────────────────────────────
        fist_start = None
        fist_active = False
        fist_hold = config["fist_hold_time"]

        # ── frame loop ─────────────────────────────────────────────────
        prev_time = time.time()
        last_ts = -1

        while not self._stop_event.is_set():
            # Check for pause command
            if not self._paused_event.is_set():
                self._paused_event.wait(timeout=0.5)
                if self._stop_event.is_set():
                    break
                prev_time = time.time()  # reset FPS clock after unpause
                continue

            # Process toggle commands from menubar
            cmds = self._state.consume_toggles()

            if cmds["toggle_hud"]:
                self._state._apply_toggle_hud()
                if self._state.hud_visible:
                    hud.show(text=current_mode.name)
                else:
                    hud.hide()

            if cmds["toggle_orb"]:
                self._state._apply_toggle_orb()
                if self._state.orb_visible:
                    hud.show_orb()
                else:
                    hud.hide_orb()

            if cmds["toggle_voice_always_on"]:
                self._state._apply_toggle_voice_always_on()
                if voice_mode is not None:
                    if self._state.voice_always_on:
                        voice_mode._always_on = True
                        if voice_mode._pipeline and not voice_mode._pipeline.is_listening():
                            voice_mode._pipeline.start()
                    else:
                        voice_mode._always_on = False
                        if voice_mode._pipeline and voice_mode._pipeline.is_listening():
                            voice_mode._pipeline.stop()

            if cmds["toggle_voice_mute"]:
                self._state._apply_toggle_voice_mute()
                if voice_mode is not None and voice_mode._pipeline:
                    if self._state.voice_muted:
                        voice_mode._pipeline.stop()
                    elif self._state.voice_always_on:
                        voice_mode._pipeline.start()

            # ── capture frame ──────────────────────────────────────────
            ok, frame = cap.read()
            if not ok:
                self._state.set_error("Camera read failed. Device disconnected?")
                break

            frame = cv2.flip(frame, 1)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            ts = int(time.time() * 1000)
            last_ts = max(ts, last_ts + 1)
            now = time.time()

            result = detect(landmarker, rgb, last_ts)
            height, width = frame.shape[:2]

            gesture_name = ""
            landmarks = None
            fingers = [False] * 5

            if result.hand_landmarks:
                landmarks = result.hand_landmarks[0]
                # draw_hand writes into the frame (harmless, not displayed)
                draw_hand(frame, landmarks)
                fingers = fingers_up(landmarks)
                gesture_name = name_gesture(fingers)

            # ── mode switching: fist detection ─────────────────────────
            if gesture_name == "Fist":
                if fist_start is None:
                    fist_start = now
                elif now - fist_start >= fist_hold and not fist_active:
                    current_mode.exit()
                    current_idx = (current_idx + 1) % len(self._mode_order)
                    current_mode = modes[self._mode_order[current_idx]]
                    current_mode.enter()
                    self._current_mode = current_mode
                    fist_active = True
                    if self._state.hud_visible:
                        hud.show(text=current_mode.name, level=100)
            else:
                fist_start = None
                fist_active = False

            # ── dispatch to current mode ───────────────────────────────
            gd = GestureData(
                gesture_name=gesture_name, fingers_up=fingers,
                landmarks=landmarks, frame=frame,
                width=width, height=height, timestamp=now,
            )
            hud_data = current_mode.update(gd)

            # Update HUD if visible
            if self._state.hud_visible and hud_data:
                hud.show(**hud_data)

            # ── update orb state ───────────────────────────────────────
            if self._state.orb_visible and _orb_available:
                orb_state = _compute_orb_state(current_mode, gesture_name, OrbState)
                if orb_state is not None:
                    hud.set_orb_state(orb_state)

            # ── update shared state for menubar polling ────────────────
            fps = 1.0 / max(now - prev_time, 1e-6)
            prev_time = now
            mode_display = current_mode.name
            hand_display = gesture_name if gesture_name else ""
            self._state.set_status(mode_display, fps, hand_display)

        # ── cleanup ────────────────────────────────────────────────────
        current_mode.exit()
        cap.release()
        landmarker.close()
        hud.close()
        cv2.destroyAllWindows()


# ── Orb state helper (used by the controller loop) ─────────────────────

def _compute_orb_state(mode, gesture_name: str, OrbState) -> Optional[object]:
    """Determine orb visual state from current mode and gesture context."""
    if not gesture_name:
        return OrbState.IDLE

    if mode.name == "Voice":
        if getattr(mode, "error", None) or getattr(mode, "_error", None):
            return OrbState.ERROR
        if getattr(mode, "listening", False):
            return OrbState.LISTENING
        if getattr(mode, "processing", False) or getattr(mode, "thinking", False):
            return OrbState.THINKING
        if getattr(mode, "speaking", False):
            return OrbState.SPEAKING
        return OrbState.IDLE

    if getattr(mode, "error", None) or getattr(mode, "_error", None):
        return OrbState.ERROR

    return OrbState.IDLE


# ═══════════════════════════════════════════════════════════════════════════
# Menu bar app (rumps)
# ═══════════════════════════════════════════════════════════════════════════

class GestureControlApp:
    """Menu bar app for GestureControl.

    Manages the gesture-processing background thread and provides a
    status-icon + menu for toggling features.
    """

    def __init__(self):
        import rumps
        self._rumps = rumps
        self._state = _SharedState()
        self._controller = GestureController(self._state)
        self._last_icon = ""

        # Build initial icon
        icon = _make_icon("off") or None

        self.app = rumps.App(
            name="GestureControl",
            title=None,
            icon=icon,
            template=False,          # we draw our own colours
            quit_button=None,        # custom Quit does full shutdown
        )

        # Accessibility label for VoiceOver
        try:
            button = self.app._nsapp.statusItem.button()
            button.setAccessibilityLabel_("GestureControl: inactive")
        except Exception:
            pass

        # ── menu items ─────────────────────────────────────────────────
        self._status_item = rumps.MenuItem("...", callback=None)
        self._hud_item = rumps.MenuItem("Show HUD", callback=self._on_toggle_hud)
        self._orb_item = rumps.MenuItem("Show Orb", callback=self._on_toggle_orb)
        self._voice_always_on_item = rumps.MenuItem(
            "Voice always-on", callback=self._on_toggle_voice_always_on)
        self._voice_mute_item = rumps.MenuItem(
            "Mute voice", callback=self._on_toggle_voice_mute)
        self._fps_hand_item = rumps.MenuItem("...", callback=None)
        self._quit_item = rumps.MenuItem(
            "Quit GestureControl", callback=self._on_quit)

        # Section headers (dimmed labels)
        self._hdr_status = rumps.MenuItem("Status", callback=None)

        self.app.menu = [
            self._status_item,
            None,  # separator
            self._hdr_status,
            self._hud_item,
            self._orb_item,
            self._voice_always_on_item,
            self._voice_mute_item,
            None,  # separator
            self._fps_hand_item,
            None,  # separator
            self._quit_item,
        ]

        # Dim section headers
        for hdr in (self._hdr_status,):
            try:
                hdr._menuitem.setEnabled_(False)
            except Exception:
                pass

        # Start the gesture controller in background thread
        self._controller.start()

        # Poll timer
        self._timer = rumps.Timer(self._on_timer, 2)
        self._timer.start()

        # Initial menu sync
        self._update_menu()

    # ── timer callback (main thread) ───────────────────────────────────

    def _on_timer(self, _=None):
        """Called every 2s by rumps.Timer on the main thread."""
        self._update_menu()

    def _update_menu(self):
        """Refresh all menu items and icon from shared state."""
        s = self._state.snapshot()

        # ── icon ───────────────────────────────────────────────────────
        if s["error"]:
            icon_state = "error"
        elif s["running"]:
            icon_state = "active"
        else:
            icon_state = "off"

        new_icon = _make_icon(icon_state)
        if new_icon and new_icon != self._last_icon:
            self.app.icon = new_icon
            self._last_icon = new_icon

        # ── status line ────────────────────────────────────────────────
        if s["error"]:
            status = f"●  Error — {s['error'][:40]}"
        elif s["running"]:
            status = f"●  Active — {s['mode']}"
        else:
            status = "○  Off"

        self._status_item.title = status

        # ── toggle items with checkmarks ───────────────────────────────
        self._hud_item.state = 1 if s["hud_visible"] else 0
        self._orb_item.state = 1 if s["orb_visible"] else 0
        self._voice_always_on_item.state = 1 if s["voice_always_on"] else 0
        # Mute is "checked" when muted
        self._voice_mute_item.state = 1 if s["voice_muted"] else 0

        # ── FPS + hand line ────────────────────────────────────────────
        fps_str = f"{s['fps']:4.0f}" if s["fps"] > 0 else "--"
        hand_str = s["hand"] if s["hand"] else "No hand"
        self._fps_hand_item.title = f"FPS: {fps_str}  |  Hand: {hand_str}"

        # ── accessibility label ────────────────────────────────────────
        try:
            button = self.app._nsapp.statusItem.button()
            if s["error"]:
                label = f"GestureControl: error — {s['error'][:60]}"
            elif s["running"]:
                label = f"GestureControl: active, {s['mode']}"
            else:
                label = "GestureControl: inactive"
            button.setAccessibilityLabel_(label)
        except Exception:
            pass

    # ── toggle callbacks ───────────────────────────────────────────────

    def _on_toggle_hud(self, _):
        self._state.request_toggle_hud()
        time.sleep(0.15)  # let background thread consume
        self._update_menu()

    def _on_toggle_orb(self, _):
        self._state.request_toggle_orb()
        time.sleep(0.15)
        self._update_menu()

    def _on_toggle_voice_always_on(self, _):
        self._state.request_toggle_voice_always_on()
        time.sleep(0.15)
        self._update_menu()

    def _on_toggle_voice_mute(self, _):
        self._state.request_toggle_voice_mute()
        time.sleep(0.15)
        self._update_menu()

    # ── quit ───────────────────────────────────────────────────────────

    def _on_quit(self, _):
        """Stop gesture tracking and exit the menubar app."""
        self._notify("GestureControl", "Shutting down",
                      "Stopping gesture tracking...")
        self._timer.stop()
        self._controller.stop(timeout=3.0)
        self._notify("GestureControl", "Goodbye", "GestureControl stopped.")
        self._rumps.quit_application()

    # ── helpers ────────────────────────────────────────────────────────

    def _notify(self, title: str, subtitle: str, message: str):
        """Send a macOS notification (best-effort, ignores errors)."""
        try:
            self._rumps.notification(title, subtitle, message, sound=False)
        except Exception:
            pass

    def run(self):
        """Start the rumps event loop (main thread). Blocks until quit."""
        self.app.run()


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    GestureControlApp().run()


if __name__ == "__main__":
    main()
