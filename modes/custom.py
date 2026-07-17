# modes/custom.py
import subprocess
import pyautogui
from modes.base import Mode, GestureData
import time


class CustomMode(Mode):
    name = "Custom"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._mappings = config.get("custom_gestures", {})
        self._last_action = {}

    def update(self, gesture: GestureData):
        name = gesture.gesture_name
        if name not in self._mappings:
            return {"text": name or "—", "level": None}

        action = self._mappings[name]
        now = time.time()
        if name in self._last_action and now - self._last_action[name] < 1.5:
            return {"text": name, "level": None}  # cooldown

        self._last_action[name] = now
        action_type = action.get("action")

        if action_type == "keyboard_shortcut":
            keys = action.get("keys", [])
            if keys:
                pyautogui.hotkey(*keys)
            return {"text": f"{name}: {'+'.join(keys)}", "level": 100}

        elif action_type == "open_app":
            path = action.get("path", "")
            if path:
                subprocess.Popen(["open", path])
            return {"text": f"{name}: open", "level": 100}

        elif action_type == "shell":
            cmd = action.get("command", "")
            if cmd:
                subprocess.Popen(cmd, shell=True)
            return {"text": f"{name}: cmd", "level": 100}

        return {"text": name, "level": None}
