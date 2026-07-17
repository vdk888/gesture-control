"""SystemMode -- combined volume, brightness, and media control.

Merges the old VolumeMode, BrightnessMode, and MediaMode into a single mode.
Point index finger = volume (x-axis). Two fingers = brightness. Open palm
hold 0.4s = play/pause.
"""

import subprocess
import threading

from modes.base import Mode, GestureData

try:
    import Quartz
    from AppKit import NSEvent
    MEDIA_OK = True
except ImportError:
    MEDIA_OK = False


class SystemMode(Mode):
    name = "System"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        # Volume state (background thread, same pattern as VolumeMode)
        self._vol_level = self._read_volume()
        self._vol_lock = threading.Lock()
        self._vol_stop = False
        self._vol_stop_event = threading.Event()
        self._vol_thread = threading.Thread(target=self._vol_run, daemon=True)
        self._vol_thread.start()
        # Brightness state
        self._brightness_level = self._read_brightness()
        # Media state
        self._palm_start = None
        self._palm_fired = False

    # -- volume helpers --------------------------------------------------

    @staticmethod
    def _read_volume():
        try:
            out = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=2,
            )
            val = out.stdout.strip()
            return int(val) if val else 50
        except (ValueError, subprocess.SubprocessError):
            return 50

    def _vol_run(self):
        while not self._vol_stop:
            with self._vol_lock:
                target = self._vol_level
            try:
                current = self._read_volume()
                if abs(current - target) > 2:
                    subprocess.run(
                        ["osascript", "-e",
                         f"set volume output volume {target}"],
                        capture_output=True, timeout=2,
                    )
            except subprocess.SubprocessError:
                pass
            self._vol_stop_event.wait(0.1)

    # -- brightness helpers ----------------------------------------------

    @staticmethod
    def _read_brightness():
        try:
            out = subprocess.run(
                ["osascript", "-e",
                 "tell application \"System Events\" to get value of "
                 "attribute \"AXValue\" of slider 1 of group 2 of "
                 "window 1 of application process \"ControlCenter\""],
                capture_output=True, text=True, timeout=3,
            )
            return int(float(out.stdout.strip()) * 100)
        except (ValueError, subprocess.SubprocessError):
            return 50

    def _set_brightness(self, level):
        try:
            subprocess.run(
                ["osascript", "-e",
                 f"tell application \"System Events\" to repeat {int(level / 10) + 1} times\n"
                 "  key code 144\n"
                 "end repeat"],
                capture_output=True, timeout=2,
            )
        except subprocess.SubprocessError:
            pass

    # -- media helpers ---------------------------------------------------

    def _send_play_pause(self):
        if not MEDIA_OK:
            return
        for down in (True, False):
            flags = 0xA00 if down else 0xB00
            data1 = (16 << 16) | ((0xA if down else 0xB) << 8)
            event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), flags, 0, 0, None, 8, data1, -1)
            Quartz.CGEventPost(0, event.CGEvent())

    # -- lifecycle -------------------------------------------------------

    def enter(self):
        super().enter()
        self._palm_start = None
        self._palm_fired = False

    def exit(self):
        super().exit()
        self._vol_stop = True
        self._vol_stop_event.set()

    # -- per-frame update ------------------------------------------------

    def update(self, gesture: GestureData):
        if gesture.landmarks is None:
            self._palm_start = None
            self._palm_fired = False
            return {"text": "", "level": None}

        lm = gesture.landmarks
        now = gesture.timestamp

        # Point index finger → Volume (x-axis position)
        if gesture.gesture_name == "Pointing":
            return self._handle_volume(lm)

        # Two fingers → Brightness (x-axis position)
        elif gesture.gesture_name == "Two fingers":
            return self._handle_brightness(lm)

        # Open palm hold 0.4s → Play/Pause
        elif gesture.gesture_name == "Open palm":
            return self._handle_media(now)

        # Any other gesture → reset media state
        self._palm_start = None
        self._palm_fired = False
        return {"text": "", "level": None}

    def _handle_volume(self, lm):
        tip_x = lm[8].x
        span = max(0.0, min(1.0, (tip_x - 0.10) / 0.80))
        target = int(span * 100)
        with self._vol_lock:
            self._vol_level = target
        return {"text": f"\U0001f50a {self._vol_level}%", "level": self._vol_level}

    def _handle_brightness(self, lm):
        tip_x = lm[8].x
        span = max(0.0, min(1.0, (tip_x - 0.10) / 0.80))
        self._brightness_level = int(span * 100)
        self._set_brightness(self._brightness_level)
        return {"text": f"☀️ {self._brightness_level}%", "level": self._brightness_level}

    def _handle_media(self, now):
        if self._palm_start is None:
            self._palm_start = now
        elif not self._palm_fired and now - self._palm_start >= 0.4:
            self._send_play_pause()
            self._palm_fired = True
            return {"text": "Play/Pause", "level": 75}
        return {"text": "", "level": None}
