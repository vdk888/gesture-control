# modes/spaces.py
import pyautogui
from modes.base import Mode, GestureData
import time

pyautogui.PAUSE = 0

class SpacesMode(Mode):
    name = "Spaces"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._swipe_cooldown = 0

    def update(self, gesture: GestureData):
        now = time.time()
        if gesture.gesture_name != "Open palm" or now - self._swipe_cooldown < 0.8:
            return {"text": "", "level": None}

        # Determine swipe direction from hand position relative to previous
        if gesture.landmarks is not None:
            wrist_y = gesture.landmarks[0].y
            wrist_x = gesture.landmarks[0].x

            if wrist_y < 0.3:
                pyautogui.hotkey("ctrl", "up")    # Mission Control
                self._swipe_cooldown = now
                return {"text": "Mission Control", "level": 80}
            elif wrist_y > 0.7:
                pyautogui.hotkey("fn", "f11")     # Show Desktop
                self._swipe_cooldown = now
                return {"text": "Show Desktop", "level": 80}
            elif wrist_x < 0.3:
                pyautogui.hotkey("ctrl", "left")  # Previous Space
                self._swipe_cooldown = now
                return {"text": "← Space", "level": 80}
            elif wrist_x > 0.7:
                pyautogui.hotkey("ctrl", "right") # Next Space
                self._swipe_cooldown = now
                return {"text": "Space →", "level": 80}

        return {"text": "", "level": None}
