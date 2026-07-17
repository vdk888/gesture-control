# modes/brightness.py
import subprocess
from modes.base import Mode, GestureData


class BrightnessMode(Mode):
    name = "Brightness"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._level = self._read_brightness()

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

    def update(self, gesture: GestureData):
        if gesture.landmarks is None:
            return {"text": f"{self._level}%", "level": self._level}

        # Use index finger tip x position — works regardless of gesture name
        tip_x = gesture.landmarks[8].x
        span = max(0.0, min(1.0, (tip_x - 0.10) / 0.80))
        self._level = int(span * 100)

        # Set brightness via osascript (works on all Macs)
        try:
            subprocess.run(
                ["osascript", "-e",
                 f"tell application \"System Events\" to repeat {int(self._level / 10) + 1} times\n"
                 "  key code 144\n"
                 "end repeat"],
                capture_output=True, timeout=2,
            )
        except subprocess.SubprocessError:
            pass

        return {"text": f"☀️ {self._level}%", "level": self._level}
