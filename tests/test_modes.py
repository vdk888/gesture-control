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
