# modes/scroll.py
import pyautogui
from modes.base import Mode, GestureData

class ScrollMode(Mode):
    name = "Scroll"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._last_y = None

    def update(self, gesture: GestureData):
        if gesture.landmarks is None or gesture.gesture_name != "Two fingers":
            self._last_y = None
            return {"text": "", "level": None}

        # Index + middle finger tips midpoint
        idx_y = gesture.landmarks[8].y
        mid_y = gesture.landmarks[12].y
        avg_y = (idx_y + mid_y) / 2.0

        if self._last_y is not None:
            dy = (self._last_y - avg_y) * 100  # scale to scroll units
            pyautogui.scroll(int(dy))

        self._last_y = avg_y
        direction = "▲" if self._last_y is None or avg_y < 0.5 else "▼"
        return {"text": f"Scroll {direction}", "level": None}

    def exit(self):
        super().exit()
        self._last_y = None
