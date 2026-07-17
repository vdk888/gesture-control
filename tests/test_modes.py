import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modes.base import GestureData
from modes.mouse import MouseMode
from config_manager import DEFAULT_CONFIG


class FakeLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class FakeHUD:
    def __init__(self):
        self.updates = []

    def show(self, **kw):
        self.updates.append(kw)


def test_mouse_mode_name():
    mode = MouseMode(DEFAULT_CONFIG)
    assert mode.name == "Mouse"


def test_mouse_update_no_hand():
    mode = MouseMode(DEFAULT_CONFIG)
    g = GestureData(gesture_name="", fingers_up=[], landmarks=None,
                    frame=None, width=640, height=480, timestamp=0)
    result = mode.update(g)
    # Should not crash, no HUD update for no hand
    assert result is None


def test_mouse_update_pointing_produces_position():
    mode = MouseMode(DEFAULT_CONFIG)
    lm = [FakeLandmark(0.5, 0.5) for _ in range(21)]
    lm[8] = FakeLandmark(0.3, 0.3)  # index tip
    g = GestureData(gesture_name="Pointing", fingers_up=[False, True, False, False, False],
                    landmarks=lm, frame=None, width=640, height=480, timestamp=1000.0)
    result = mode.update(g)
    # With first frame, position initializes
    assert mode._cx is not None


# ── CustomMode tests ──────────────────────────────────────────────

from modes.custom import CustomMode
import time


def test_custom_mode_name():
    config = {"custom_gestures": {}}
    mode = CustomMode(config)
    assert mode.name == "Custom"


def test_custom_unmapped_gesture_returns_none_level():
    config = {"custom_gestures": {"Fist": {"action": "keyboard_shortcut", "keys": ["cmd", "s"]}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Pointing", fingers_up=[False, True, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=0)
    result = mode.update(g)
    assert result == {"text": "Pointing", "level": None}


def test_custom_unmapped_empty_name_returns_dash():
    config = {"custom_gestures": {}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="", fingers_up=[], landmarks=None, frame=None,
                    width=640, height=480, timestamp=0)
    result = mode.update(g)
    assert result == {"text": "—", "level": None}


def test_custom_keyboard_shortcut(monkeypatch):
    called_keys = None

    def fake_hotkey(*keys):
        nonlocal called_keys
        called_keys = keys

    monkeypatch.setattr("modes.custom.pyautogui.hotkey", fake_hotkey)

    config = {"custom_gestures": {"Fist": {"action": "keyboard_shortcut", "keys": ["cmd", "s"]}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    result = mode.update(g)
    assert called_keys == ("cmd", "s")
    assert result == {"text": "Fist: cmd+s", "level": 100}


def test_custom_keyboard_shortcut_empty_keys_does_not_call(monkeypatch):
    call_count = 0

    def fake_hotkey(*keys):
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr("modes.custom.pyautogui.hotkey", fake_hotkey)

    config = {"custom_gestures": {"Fist": {"action": "keyboard_shortcut", "keys": []}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    mode.update(g)
    assert call_count == 0


def test_custom_open_app(monkeypatch):
    called_args = None

    def fake_popen(args, shell=False):
        nonlocal called_args
        called_args = args
        return type("Popen", (), {"wait": lambda: None})()

    monkeypatch.setattr("modes.custom.subprocess.Popen", fake_popen)

    config = {"custom_gestures": {"Open palm": {"action": "open_app", "path": "/Applications/Safari.app"}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Open palm", fingers_up=[True, True, True, True, True],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    result = mode.update(g)
    assert called_args == ["open", "/Applications/Safari.app"]
    assert result == {"text": "Open palm: open", "level": 100}


def test_custom_open_app_empty_path_does_not_call(monkeypatch):
    call_count = 0

    def fake_popen(args, shell=False):
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr("modes.custom.subprocess.Popen", fake_popen)

    config = {"custom_gestures": {"Open palm": {"action": "open_app", "path": ""}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Open palm", fingers_up=[True, True, True, True, True],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    mode.update(g)
    assert call_count == 0


def test_custom_shell_command(monkeypatch):
    called_cmd = None
    called_shell = None

    def fake_popen(cmd, shell=False):
        nonlocal called_cmd, called_shell
        called_cmd = cmd
        called_shell = shell
        return type("Popen", (), {"wait": lambda: None})()

    monkeypatch.setattr("modes.custom.subprocess.Popen", fake_popen)

    config = {"custom_gestures": {"Fist": {"action": "shell", "command": "say hello"}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    result = mode.update(g)
    assert called_cmd == "say hello"
    assert called_shell is True
    assert result == {"text": "Fist: cmd", "level": 100}


def test_custom_shell_empty_command_does_not_call(monkeypatch):
    call_count = 0

    def fake_popen(cmd, shell=False):
        nonlocal call_count
        call_count += 1

    monkeypatch.setattr("modes.custom.subprocess.Popen", fake_popen)

    config = {"custom_gestures": {"Fist": {"action": "shell", "command": ""}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    mode.update(g)
    assert call_count == 0


def test_custom_cooldown_blocks_repeat(monkeypatch):
    """Second call within 1.5s should return None level and not trigger action."""
    call_count = 0
    fake_now = [1000.0]

    def fake_hotkey(*keys):
        nonlocal call_count
        call_count += 1

    def fake_time():
        return fake_now[0]

    monkeypatch.setattr("modes.custom.pyautogui.hotkey", fake_hotkey)
    monkeypatch.setattr("modes.custom.time.time", fake_time)

    config = {"custom_gestures": {"Fist": {"action": "keyboard_shortcut", "keys": ["cmd", "s"]}}}
    mode = CustomMode(config)

    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=1000.0)

    r1 = mode.update(g)
    assert call_count == 1
    assert r1["level"] == 100

    # Same gesture 0.5s later — cooldown
    fake_now[0] = 1000.5
    g2 = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                     landmarks=None, frame=None, width=640, height=480, timestamp=1000.5)
    r2 = mode.update(g2)
    assert call_count == 1  # still 1, not called again
    assert r2 == {"text": "Fist", "level": None}


def test_custom_cooldown_allows_after_delay(monkeypatch):
    """After 1.5s+ the action fires again."""
    call_count = 0
    fake_now = [1000.0]

    def fake_hotkey(*keys):
        nonlocal call_count
        call_count += 1

    def fake_time():
        return fake_now[0]

    monkeypatch.setattr("modes.custom.pyautogui.hotkey", fake_hotkey)
    monkeypatch.setattr("modes.custom.time.time", fake_time)

    config = {"custom_gestures": {"Fist": {"action": "keyboard_shortcut", "keys": ["cmd", "s"]}}}
    mode = CustomMode(config)

    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=1000.0)
    mode.update(g)
    assert call_count == 1

    # 2.0s later — should fire again
    fake_now[0] = 1002.0
    g2 = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                     landmarks=None, frame=None, width=640, height=480, timestamp=1002.0)
    r2 = mode.update(g2)
    assert call_count == 2
    assert r2["level"] == 100


def test_custom_unknown_action_returns_none_level():
    config = {"custom_gestures": {"Fist": {"action": "bogus_action"}}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    result = mode.update(g)
    assert result == {"text": "Fist", "level": None}


def test_custom_empty_mappings_handles_any_gesture():
    config = {"custom_gestures": {}}
    mode = CustomMode(config)
    g = GestureData(gesture_name="Fist", fingers_up=[True, False, False, False, False],
                    landmarks=None, frame=None, width=640, height=480, timestamp=100.0)
    result = mode.update(g)
    assert result == {"text": "Fist", "level": None}
