# modes/media.py
from modes.base import Mode, GestureData
import time
try:
    import Quartz
    from AppKit import NSEvent
    MEDIA_OK = True
except ImportError:
    MEDIA_OK = False

class MediaMode(Mode):
    name = "Media"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._palm_start = None
        self._fired = False
        self._last_action = 0

    def update(self, gesture: GestureData):
        if not MEDIA_OK:
            return {"text": "Media keys unavailable", "level": None}

        now = gesture.timestamp
        if gesture.gesture_name == "Open palm":
            if self._palm_start is None:
                self._palm_start = now
            elif not self._fired and now - self._palm_start >= 0.4:
                self._send_play_pause()
                self._fired = True
                self._last_action = now
                return {"text": "Play/Pause", "level": 75}
        else:
            self._palm_start = None
            self._fired = False

        return {"text": "", "level": None}

    def _send_play_pause(self):
        for down in (True, False):
            flags = 0xA00 if down else 0xB00
            data1 = (16 << 16) | ((0xA if down else 0xB) << 8)
            event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), flags, 0, 0, None, 8, data1, -1)
            Quartz.CGEventPost(0, event.CGEvent())
