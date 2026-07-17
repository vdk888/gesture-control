"""Tests for modes/base.py — Mode ABC and GestureData dataclass."""

import time
import pytest
from modes.base import Mode, GestureData


class TestGestureData:
    """GestureData is a plain dataclass — verify construction and defaults."""

    def test_default_hand_index(self):
        gd = GestureData(
            gesture_name="Fist",
            fingers_up=[True, False, False, False, False],
            landmarks=None,
            frame=None,
            width=640,
            height=480,
            timestamp=time.time(),
        )
        assert gd.hand_index == 0

    def test_explicit_hand_index(self):
        gd = GestureData(
            gesture_name="Pointing",
            fingers_up=[False, True, False, False, False],
            landmarks=None,
            frame=None,
            width=1280,
            height=720,
            timestamp=time.time(),
            hand_index=1,
        )
        assert gd.hand_index == 1

    def test_all_fields_accessible(self):
        ts = time.time()
        gd = GestureData(
            gesture_name="Open palm",
            fingers_up=[True, True, True, True, True],
            landmarks=[1, 2, 3],
            frame="fake_frame",
            width=1920,
            height=1080,
            timestamp=ts,
            hand_index=0,
        )
        assert gd.gesture_name == "Open palm"
        assert gd.fingers_up == [True, True, True, True, True]
        assert gd.landmarks == [1, 2, 3]
        assert gd.frame == "fake_frame"
        assert gd.width == 1920
        assert gd.height == 1080
        assert gd.timestamp == ts
        assert gd.hand_index == 0


class TestModeABC:
    """Mode is an ABC — verify abstractness and concrete subclass behavior."""

    def test_cannot_instantiate_abstract_mode(self):
        with pytest.raises(TypeError):
            Mode(config={})  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        class FakeMode(Mode):
            @property
            def name(self) -> str:
                return "Fake"

            def update(self, gesture: GestureData):
                return {"text": "ok", "level": 50}

        mode = FakeMode(config={"speed": 2.0})
        assert mode.name == "Fake"
        assert mode._active is False

    def test_enter_and_exit_toggle_active(self):
        class FakeMode(Mode):
            @property
            def name(self) -> str:
                return "Toggle"

            def update(self, gesture: GestureData):
                return None

        mode = FakeMode(config={})
        assert mode._active is False

        mode.enter()
        assert mode._active is True

        mode.exit()
        assert mode._active is False

    def test_hud_is_stored(self):
        class FakeMode(Mode):
            @property
            def name(self) -> str:
                return "HUD"

            def update(self, gesture: GestureData):
                return None

        fake_hud = object()
        mode = FakeMode(config={}, hud=fake_hud)
        assert mode.hud is fake_hud

    def test_config_is_stored(self):
        class FakeMode(Mode):
            @property
            def name(self) -> str:
                return "Config"

            def update(self, gesture: GestureData):
                return None

        cfg = {"threshold": 0.8, "smoothing": True}
        mode = FakeMode(config=cfg)
        assert mode.config is cfg
        assert mode.config["threshold"] == 0.8

    def test_missing_name_property_causes_type_error(self):
        class BadMode(Mode):
            def update(self, gesture: GestureData):
                return None

        with pytest.raises(TypeError):
            BadMode(config={})  # type: ignore[abstract]

    def test_missing_update_method_causes_type_error(self):
        class BadMode(Mode):
            @property
            def name(self) -> str:
                return "Bad"

        with pytest.raises(TypeError):
            BadMode(config={})  # type: ignore[abstract]

    def test_update_receives_gesture_data(self):
        class TrackingMode(Mode):
            @property
            def name(self) -> str:
                return "Tracking"

            def update(self, gesture: GestureData):
                return {
                    "text": gesture.gesture_name,
                    "level": sum(gesture.fingers_up) * 20,
                }

        mode = TrackingMode(config={})
        gd = GestureData(
            gesture_name="Pointing",
            fingers_up=[False, True, False, False, False],
            landmarks=None,
            frame=None,
            width=640,
            height=480,
            timestamp=time.time(),
        )
        result = mode.update(gd)
        assert result is not None
        assert result["text"] == "Pointing"
        assert result["level"] == 20  # 1 finger * 20
