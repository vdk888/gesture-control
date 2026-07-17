# modes/brightness.py
import subprocess
from modes.base import Mode, GestureData

class BrightnessMode(Mode):
    name = "Brightness"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._level = 50

    def update(self, gesture: GestureData):
        if gesture.landmarks is None or gesture.gesture_name != "Pointing":
            return {"text": f"{self._level}%", "level": self._level}

        tip_x = gesture.landmarks[8].x
        span = max(0.0, min(1.0, (tip_x - 0.15) / 0.70))
        self._level = int(span * 100)
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'tell app "System Events" to repeat 10 times'
                 f'\n  key code 145\nend repeat'],
                timeout=1,
            )
        except subprocess.SubprocessError:
            pass
        # Use the brightness slider approach instead
        try:
            subprocess.run(
                ["brightness", str(float(self._level) / 100.0)], timeout=1)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return {"text": f"{self._level}%", "level": self._level}
