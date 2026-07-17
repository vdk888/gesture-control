# modes/volume.py
import subprocess
import threading
import time
from modes.base import Mode, GestureData


class VolumeMode(Mode):
    name = "Volume"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._level = self._read_volume()
        self._lock = threading.Lock()
        self._stop = False
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

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

    def update(self, gesture: GestureData):
        if gesture.landmarks is None:
            return {"text": f"{self._level}%", "level": self._level}

        # Use index finger tip x position to set volume — works regardless
        # of gesture name, as long as we have a hand in frame.
        tip_x = gesture.landmarks[8].x
        span = max(0.0, min(1.0, (tip_x - 0.10) / 0.80))
        target = int(span * 100)
        with self._lock:
            self._level = target
        return {"text": f"🔊 {self._level}%", "level": self._level}

    def _run(self):
        while not self._stop:
            with self._lock:
                target = self._level
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
            self._stop_event.wait(0.1)

    def exit(self):
        super().exit()
        self._stop = True
        self._stop_event.set()
