# modes/volume.py
import subprocess
import threading
from modes.base import Mode, GestureData


class VolumeMode(Mode):
    name = "Volume"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._level = self._read_volume()
        self._lock = threading.Lock()
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @staticmethod
    def _read_volume():
        try:
            out = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=2,
            )
            return int(out.stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            return 50

    def update(self, gesture: GestureData):
        if gesture.landmarks is None or gesture.gesture_name != "Pointing":
            return {"text": f"{self._level}%", "level": self._level}

        tip_x = gesture.landmarks[8].x
        # Map tip x position (0.15-0.85) to 0-100 volume
        span = max(0.0, min(1.0, (tip_x - 0.15) / 0.70))
        target = int(span * 100)
        with self._lock:
            self._level = target
        return {"text": f"{self._level}%", "level": self._level}

    def _run(self):
        while not self._stop:
            with self._lock:
                target = self._level
            try:
                current = self._read_volume()
                if abs(current - target) > 1:
                    subprocess.run(
                        ["osascript", "-e", f"set volume output volume {target}"],
                        timeout=2,
                    )
            except subprocess.SubprocessError:
                pass
            self._stop_event = threading.Event()
            self._stop_event.wait(0.05)

    def exit(self):
        super().exit()
        self._stop = True
