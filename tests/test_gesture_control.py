"""Integration tests for gesture_control.py — the main app entry point."""

import sys
import os
import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import gesture_control
from gesture_control import main
from modes.base import GestureData, Mode
from config_manager import DEFAULT_CONFIG
from hand_tracking import name_gesture as real_name_gesture


# ── Fake / mock helpers ────────────────────────────────────────────────


class FakeMode(Mode):
    """A minimal Mode subclass for testing the main loop logic."""

    _name = "FakeMode"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self.updates = []
        self.enter_calls = 0
        self.exit_calls = 0

    @property
    def name(self) -> str:
        return self._name

    def enter(self):
        super().enter()
        self.enter_calls += 1

    def exit(self):
        super().exit()
        self.exit_calls += 1

    def update(self, gesture: GestureData):
        self.updates.append(gesture)
        return {"text": self._name, "level": None}


class FakeHUD:
    """Tracks HUD calls without needing AppKit."""

    def __init__(self):
        self.shows = []

    def show(self, **kwargs):
        self.shows.append(kwargs)

    def close(self):
        pass


class FakeLandmark:
    """Minimal landmark stub with x, y attributes."""

    def __init__(self, x, y):
        self.x = x
        self.y = y


class FakeHandResult:
    """Mimics MediaPipe HandLandmarkerResult."""

    def __init__(self, landmarks=None):
        self.hand_landmarks = [landmarks] if landmarks else []


def make_fake_hand():
    """Return a 21-landmark open-hand list (all landmarks at neutral positions)."""
    return [FakeLandmark(0.5, 0.5) for _ in range(21)]


def make_fist_landmarks():
    """Return 21 landmarks positioned to produce a Fist gesture.

    fingers_up() checks: tip farther from wrist than pip. For a fist,
    tips are closer to center (wrist is at index 0, pip for index is 6).
    We set tips to be AT the pip position and pips farther from wrist.
    """
    lm = [FakeLandmark(0.5, 0.5) for _ in range(21)]  # wrist at [0] centered
    # Place pips far from wrist (extended), tips near wrist (folded)
    # Index: pip=6, tip=8; Middle: pip=10, tip=12; Ring: pip=14, tip=16; Pinky: pip=18, tip=20
    # For thumb: pinky_mcp=17, pip=3, tip=4 - tip closer to pinky_mcp than pip
    lm[3] = FakeLandmark(0.6, 0.3)   # thumb pip - far from pinky_mcp
    lm[4] = FakeLandmark(0.42, 0.48)  # thumb tip - close to pinky_mcp (folded)
    lm[6] = FakeLandmark(0.5, 0.15)  # index pip - far from wrist
    lm[8] = FakeLandmark(0.45, 0.55)  # index tip - closer to wrist
    lm[10] = FakeLandmark(0.5, 0.15)
    lm[12] = FakeLandmark(0.45, 0.55)
    lm[14] = FakeLandmark(0.5, 0.15)
    lm[16] = FakeLandmark(0.45, 0.55)
    lm[18] = FakeLandmark(0.5, 0.15)
    lm[20] = FakeLandmark(0.45, 0.55)
    lm[17] = FakeLandmark(0.4, 0.5)   # pinky mcp
    return lm


def make_pointing_landmarks():
    """Return 21 landmarks positioned to produce a Pointing gesture."""
    lm = [FakeLandmark(0.5, 0.5) for _ in range(21)]  # wrist
    lm[6] = FakeLandmark(0.5, 0.15)   # index pip - far from wrist
    lm[8] = FakeLandmark(0.5, 0.02)   # index tip - far from wrist (extended)
    # Other fingers folded
    lm[10] = FakeLandmark(0.5, 0.15)
    lm[12] = FakeLandmark(0.45, 0.55)
    lm[14] = FakeLandmark(0.5, 0.15)
    lm[16] = FakeLandmark(0.45, 0.55)
    lm[18] = FakeLandmark(0.5, 0.15)
    lm[20] = FakeLandmark(0.45, 0.55)
    lm[17] = FakeLandmark(0.4, 0.5)
    lm[3] = FakeLandmark(0.6, 0.3)
    lm[4] = FakeLandmark(0.42, 0.48)  # thumb folded (close to pinky_mcp)
    return lm


def make_open_palm_landmarks():
    """Return 21 landmarks positioned to produce an Open palm gesture."""
    lm = [FakeLandmark(0.5, 0.5) for _ in range(21)]  # wrist
    # All tips extend upward (away from wrist)
    lm[3] = FakeLandmark(0.3, 0.45)
    lm[4] = FakeLandmark(0.15, 0.4)   # thumb tip (far from pinky_mcp)
    lm[6] = FakeLandmark(0.5, 0.15)
    lm[8] = FakeLandmark(0.5, 0.02)
    lm[10] = FakeLandmark(0.55, 0.15)
    lm[12] = FakeLandmark(0.58, 0.02)
    lm[14] = FakeLandmark(0.65, 0.15)
    lm[16] = FakeLandmark(0.68, 0.02)
    lm[18] = FakeLandmark(0.75, 0.15)
    lm[20] = FakeLandmark(0.78, 0.02)
    lm[17] = FakeLandmark(0.7, 0.5)   # pinky mcp
    return lm


# ── Module structure tests ─────────────────────────────────────────────


class TestModuleStructure:
    """Verify the gesture_control module is well-formed."""

    def test_module_has_main(self):
        assert hasattr(gesture_control, "main")
        assert callable(gesture_control.main)

    def test_module_imports_are_correct(self):
        """Verify all required imports resolve."""
        from hand_tracking import create_landmarker, detect, fingers_up, name_gesture, draw_hand  # noqa: F401
        from modes.base import GestureData  # noqa: F401
        from modes import MODE_REGISTRY  # noqa: F401
        from config_manager import load_config  # noqa: F401
        from hud import HUD  # noqa: F401


# ── Main loop integration tests with mocks ─────────────────────────────


class TestMainIntegration:
    """Test the main() function with mocked camera and MediaPipe."""

    def test_main_no_camera_graceful_exit(self):
        """When camera can't open, main() should print error and return."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap:
            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = False
            mock_cap.return_value = mock_cam

            with patch("builtins.print") as mock_print:
                result = main()

            assert result is None  # graceful return, not crash
            mock_cam.release.assert_not_called()  # never acquired
            # Should print error about webcam
            assert any("Could not open" in str(call) for call in mock_print.call_args_list)

    def test_main_no_valid_modes_exits(self):
        """When MODE_REGISTRY has no matching modes, exit cleanly."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap:
            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_cap.return_value = mock_cam

            with patch("gesture_control.create_landmarker") as mock_create:
                mock_landmarker = MagicMock()
                mock_create.return_value = mock_landmarker

                with patch("gesture_control.MODE_REGISTRY", {}):
                    with patch("builtins.print") as mock_print:
                        result = main()

                assert result is None
                mock_cam.release.assert_called_once()
                mock_landmarker.close.assert_called_once()
                assert any("No valid modes" in str(call)
                           for call in mock_print.call_args_list)

    def test_main_loop_iterates_and_dispatches(self):
        """Main loop should read frames, detect, dispatch to mode, and quit on 'q'."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1, ord("q")]), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 1.5,
                 "modes": ["mouse"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            # Frame shape: height=480, width=640, 3 channels
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.side_effect = [(True, mock_frame), (True, mock_frame)]
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            # Simulate: first frame has hand, second frame triggers 'q'
            result_with_hand = FakeHandResult(make_fake_hand())
            gesture_control.detect = MagicMock(side_effect=[result_with_hand, result_with_hand])
            gesture_control.name_gesture = MagicMock(return_value="Pointing")

            # Register fake mode
            fake_mode = FakeMode(DEFAULT_CONFIG)
            with patch.dict("gesture_control.MODE_REGISTRY", {"mouse": lambda config, hud: fake_mode}):
                main()

            # Mode should have received enter() call and at least one update()
            assert fake_mode.enter_calls >= 1
            assert len(fake_mode.updates) >= 1
            mock_cam.release.assert_called_once()
            mock_landmarker.close.assert_called_once()

    def test_main_loop_break_on_empty_frame(self):
        """Main loop should break if cap.read() returns (False, _)."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", return_value=-1), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 1.5,
                 "modes": ["mouse"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_cam.read.return_value = (False, None)  # camera disconnected
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            with patch.dict("gesture_control.MODE_REGISTRY",
                            {"mouse": lambda config, hud: FakeMode(DEFAULT_CONFIG)}):
                main()

            # Should clean up even on early exit
            mock_cam.release.assert_called_once()
            mock_landmarker.close.assert_called_once()


# ── Mode switching logic tests ─────────────────────────────────────────


class TestModeSwitching:
    """Test the fist-hold mode-switching mechanism.

    These tests need the REAL name_gesture (not a mock) because mode switching
    matches against gesture names like "Fist". Previous tests may have left
    stale mocks on gesture_control.name_gesture, so we use patch.object to
    restore the real function for these tests.
    """

    # pylint: disable=no-member
    def test_fist_hold_triggers_mode_cycle(self):
        """Holding a fist for fist_hold_time should cycle to the next mode."""
        # We drive the main loop for several frames, controlling gesture output.
        # This is a focused integration test of the mode-switching logic within main().

        # Simulate time advancing ~0.1s per frame so fist_hold elapses during fist frames.
        fake_time = [0.0]

        def advancing_time():
            fake_time[0] += 0.1
            return fake_time[0]

        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1] * 100), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.time.time", side_effect=advancing_time), \
             patch.object(gesture_control, "name_gesture", wraps=real_name_gesture), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 0.05,  # short for test
                 "modes": ["mouse", "volume"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.return_value = (True, mock_frame)
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            mode_a = FakeMode(DEFAULT_CONFIG)
            mode_a._name = "Mouse"
            mode_b = FakeMode(DEFAULT_CONFIG)
            mode_b._name = "Volume"

            # Frame sequence:
            # 1. Fist for fist_hold_time seconds → should cycle
            # 2. Then release fist → should reset state
            # 3. Then quit

            call_count = [0]

            def mock_detect(landmarker, rgb, ts):
                call_count[0] += 1
                # First frame: fist, second+: fist continues, then after cycle: release
                if call_count[0] <= 10:
                    return FakeHandResult(make_fist_landmarks())
                elif call_count[0] <= 15:
                    return FakeHandResult(make_pointing_landmarks())
                else:
                    # Trigger quit by making waitKey return ord('q')
                    return FakeHandResult(make_pointing_landmarks())

            gesture_control.detect = mock_detect

            # Override waitKey to quit after enough frames
            waitkey_returns = [-1] * 15 + [ord("q")]
            gesture_control.cv2.waitKey = MagicMock(side_effect=waitkey_returns)

            mode_factories = {
                "mouse": lambda config, hud: mode_a,
                "volume": lambda config, hud: mode_b,
            }
            with patch.dict("gesture_control.MODE_REGISTRY", mode_factories):
                main()

            # mode_a should have been entered (first mode) and then exited (fist held)
            assert mode_a.enter_calls >= 1
            # Mode b should have been entered after the cycle
            assert mode_b.enter_calls >= 1

    def test_fist_not_held_long_enough_no_cycle(self):
        """A brief fist (shorter than fist_hold_time) should NOT trigger mode switch."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1] * 10 + [ord("q")]), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 1.5,  # normal 1.5s hold
                 "modes": ["mouse", "volume"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.return_value = (True, mock_frame)
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            mode_a = FakeMode(DEFAULT_CONFIG)
            mode_a._name = "Mouse"
            mode_b = FakeMode(DEFAULT_CONFIG)
            mode_b._name = "Volume"

            call_count = [0]

            def mock_detect(landmarker, rgb, ts):
                call_count[0] += 1
                # Brief fist (1 frame only) then release
                if call_count[0] == 1:
                    return FakeHandResult(make_fist_landmarks())
                else:
                    return FakeHandResult(make_pointing_landmarks())

            gesture_control.detect = mock_detect

            mode_factories = {
                "mouse": lambda config, hud: mode_a,
                "volume": lambda config, hud: mode_b,
            }
            with patch.dict("gesture_control.MODE_REGISTRY", mode_factories):
                main()

            # Mode B should NOT have been entered — fist was too brief
            assert mode_b.enter_calls == 0
            assert mode_b.exit_calls == 0

    def test_no_hand_no_crash(self):
        """When no hand is detected, the app should continue without crashing."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1, -1, ord("q")]), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 1.5,
                 "modes": ["mouse"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.return_value = (True, mock_frame)
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            # No hand detected at all
            gesture_control.detect = MagicMock(
                side_effect=[FakeHandResult(None), FakeHandResult(None), FakeHandResult(None)]
            )

            fake_mode = FakeMode(DEFAULT_CONFIG)
            with patch.dict("gesture_control.MODE_REGISTRY",
                            {"mouse": lambda config, hud: fake_mode}):
                main()

            # Should still call update even with no hand
            assert len(fake_mode.updates) >= 1
            # First update should have no landmarks
            assert fake_mode.updates[0].landmarks is None


# ── HUD integration tests ──────────────────────────────────────────────


class TestHUDIntegration:
    """Test HUD interaction within the main loop."""

    def test_hud_disabled_config(self):
        """When hud_enabled=False, HUD should not be created."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD") as mock_hud_class, \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": False,
                 "fist_hold_time": 1.5,
                 "modes": ["mouse"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = False  # exit early
            mock_cap.return_value = mock_cam

            main()
            mock_hud_class.assert_not_called()

    def test_mode_update_hud_data_is_passed(self):
        """When mode.update() returns HUD data, it should be passed to hud.show()."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1, ord("q")]), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 1.5,
                 "modes": ["mouse"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.return_value = (True, mock_frame)
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            fake_hud = FakeHUD()
            gesture_control.HUD.return_value = fake_hud

            gesture_control.detect = MagicMock(return_value=FakeHandResult(make_fake_hand()))
            gesture_control.name_gesture = MagicMock(return_value="Pointing")

            class HUDReportingMode(FakeMode):
                def update(self, gesture):
                    super().update(gesture)
                    return {"text": "clicking", "level": 75}

            hud_mode = HUDReportingMode(DEFAULT_CONFIG)
            with patch.dict("gesture_control.MODE_REGISTRY",
                            {"mouse": lambda config, hud: hud_mode}):
                main()

            # HUD should have received at least one show() call from mode update
            assert len(fake_hud.shows) >= 1
            # And the data should include our custom dict
            assert any("clicking" in str(s) for s in fake_hud.shows)


# ── Edge case: single mode ─────────────────────────────────────────────


class TestEdgeCases:
    """Test edge-case behavior."""

    def test_single_mode_works(self):
        """With only one mode configured, the app should just use it."""
        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1, ord("q")]), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 1.5,
                 "modes": ["mouse"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.return_value = (True, mock_frame)
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            gesture_control.detect = MagicMock(return_value=FakeHandResult(make_fake_hand()))
            gesture_control.name_gesture = MagicMock(return_value="Pointing")

            fake_mode = FakeMode(DEFAULT_CONFIG)
            with patch.dict("gesture_control.MODE_REGISTRY",
                            {"mouse": lambda config, hud: fake_mode}):
                main()

            assert fake_mode.enter_calls == 1
            assert len(fake_mode.updates) >= 1

    def test_fist_hold_cycle_wraps_around(self):
        """Fist-hold on last mode should cycle back to first mode."""

        # Simulate time advancing ~0.1s per frame.
        fake_time = [0.0]

        def advancing_time():
            fake_time[0] += 0.1
            return fake_time[0]

        with patch("gesture_control.cv2.VideoCapture") as mock_cap, \
             patch("gesture_control.cv2.flip", side_effect=lambda f, _: f), \
             patch("gesture_control.cv2.cvtColor", return_value="rgb_frame"), \
             patch("gesture_control.cv2.putText"), \
             patch("gesture_control.cv2.imshow"), \
             patch("gesture_control.cv2.waitKey", side_effect=[-1] * 100), \
             patch("gesture_control.cv2.destroyAllWindows"), \
             patch("gesture_control.create_landmarker"), \
             patch("gesture_control.HUD", return_value=FakeHUD()), \
             patch("gesture_control.time.time", side_effect=advancing_time), \
             patch.object(gesture_control, "name_gesture", wraps=real_name_gesture), \
             patch("gesture_control.load_config", return_value={
                 "camera_index": 0, "camera_width": 640, "camera_height": 480,
                 "hud_enabled": True, "fist_hold_time": 0.05,
                 "modes": ["mouse", "volume"],
             }):

            mock_cam = MagicMock()
            mock_cam.isOpened.return_value = True
            mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_cam.read.return_value = (True, mock_frame)
            mock_cap.return_value = mock_cam

            mock_landmarker = MagicMock()
            gesture_control.create_landmarker.return_value = mock_landmarker

            mode_a = FakeMode(DEFAULT_CONFIG)
            mode_a._name = "Mouse"
            mode_b = FakeMode(DEFAULT_CONFIG)
            mode_b._name = "Volume"

            call_count = [0]

            def mock_detect(landmarker, rgb, ts):
                call_count[0] += 1
                if 1 <= call_count[0] <= 10:
                    return FakeHandResult(make_fist_landmarks())   # cycle to Volume
                elif 11 <= call_count[0] <= 15:
                    return FakeHandResult(make_open_palm_landmarks())  # release fist
                elif 16 <= call_count[0] <= 25:
                    return FakeHandResult(make_fist_landmarks())   # cycle back to Mouse
                else:
                    return FakeHandResult(make_pointing_landmarks())

            gesture_control.detect = mock_detect

            waitkey_returns = [-1] * 30 + [ord("q")]
            gesture_control.cv2.waitKey = MagicMock(side_effect=waitkey_returns)

            mode_factories = {
                "mouse": lambda config, hud: mode_a,
                "volume": lambda config, hud: mode_b,
            }
            with patch.dict("gesture_control.MODE_REGISTRY", mode_factories):
                main()

            # mode_a should be entered at least twice: once as initial, once after wrap
            assert mode_a.enter_calls >= 2
            assert mode_b.enter_calls >= 1
