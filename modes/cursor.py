"""CursorMode -- combined cursor movement, click, scroll, and Spaces.

Merges the old MouseMode, ScrollMode, and SpacesMode into a single mode.
Point index finger = move cursor (1Euro filter). Pinch thumb+index = left
click. Pinch thumb+middle = right click. Two fingers = scroll. Open palm +
swipe = Spaces / Mission Control.
"""

import time

import pyautogui
import Quartz
from modes.base import Mode, GestureData
from filters import OneEuroFilter

pyautogui.PAUSE = 0


class CursorMode(Mode):
    name = "Cursor"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        smooth = config["cursor_smooth"]
        self._filter_x = OneEuroFilter(freq=60, fc_min=smooth["fc_min"], beta=smooth["beta"])
        self._filter_y = OneEuroFilter(freq=60, fc_min=smooth["fc_min"], beta=smooth["beta"])
        self._cx = None
        self._cy = None
        self._pinching_left = False
        self._pinching_right = False
        self._margin = config["margin"]
        self._pinch_on = config["pinch_on"]
        self._pinch_off = config["pinch_off"]
        self._sw = None
        self._sh = None
        # Scroll state
        self._last_scroll_y = None
        # Spaces state
        self._swipe_cooldown = 0.0

    # -- lifecycle -------------------------------------------------------

    def enter(self):
        super().enter()
        self._cx = None
        self._cy = None
        self._last_scroll_y = None

    def exit(self):
        super().exit()
        self._last_scroll_y = None

    # -- per-frame update ------------------------------------------------

    def update(self, gesture: GestureData):
        if gesture.landmarks is None:
            return self._release_all_pinches()

        # Lazy screen bounds
        if self._sw is None:
            bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            self._sw = float(bounds.size.width)
            self._sh = float(bounds.size.height)

        lm = gesture.landmarks

        # Always track cursor position from index fingertip
        tip = lm[8]
        tx, ty = self._to_screen(tip.x, tip.y)
        if self._cx is None:
            self._cx, self._cy = tx, ty
            self._filter_x.filter(tx, gesture.timestamp)
            self._filter_y.filter(ty, gesture.timestamp)
        else:
            self._cx = self._filter_x.filter(tx, gesture.timestamp)
            self._cy = self._filter_y.filter(ty, gesture.timestamp)

        # Always check pinch gestures (independent of gesture name)
        self._check_pinches(lm)

        # Post cursor movement event
        if self._pinching_left:
            self._post_mouse(Quartz.kCGEventLeftMouseDragged, self._cx, self._cy)
        elif self._pinching_right:
            self._post_mouse(Quartz.kCGEventRightMouseDragged, self._cx, self._cy)
        else:
            self._post_mouse(Quartz.kCGEventMouseMoved, self._cx, self._cy)

        # Gesture-specific overlays
        if gesture.gesture_name == "Two fingers":
            return self._handle_scroll(gesture)
        elif gesture.gesture_name == "Open palm":
            return self._handle_spaces(gesture)

        # Reset scroll state when not in Two fingers
        self._last_scroll_y = None

        status = ""
        if self._pinching_left:
            status = "Left Click"
        elif self._pinching_right:
            status = "Right Click"
        return {"text": status, "level": None}

    # -- pinch detection -------------------------------------------------

    def _check_pinches(self, lm):
        from hand_tracking import _dist
        palm = _dist(lm[5], lm[17]) or 1e-6

        # Left click: thumb tip (4) + index tip (8)
        ratio_left = _dist(lm[4], lm[8]) / palm
        if not self._pinching_left and ratio_left < self._pinch_on:
            self._pinching_left = True
            self._pinching_right = False  # left-click wins
            self._post_mouse(Quartz.kCGEventLeftMouseDown, self._cx, self._cy)
        elif self._pinching_left and ratio_left > self._pinch_off:
            self._pinching_left = False
            self._post_mouse(Quartz.kCGEventLeftMouseUp, self._cx, self._cy)

        # Right click: thumb tip (4) + middle tip (12); only when left not active
        if not self._pinching_left:
            ratio_right = _dist(lm[4], lm[12]) / palm
            if not self._pinching_right and ratio_right < self._pinch_on:
                self._pinching_right = True
                self._post_mouse(Quartz.kCGEventRightMouseDown, self._cx, self._cy)
            elif self._pinching_right and ratio_right > self._pinch_off:
                self._pinching_right = False
                self._post_mouse(Quartz.kCGEventRightMouseUp, self._cx, self._cy)

    def _release_all_pinches(self):
        """Release any active pinch when hand leaves frame."""
        if self._pinching_left:
            self._pinching_left = False
            if self._cx is not None:
                self._post_mouse(Quartz.kCGEventLeftMouseUp, self._cx, self._cy)
        if self._pinching_right:
            self._pinching_right = False
            if self._cx is not None:
                self._post_mouse(Quartz.kCGEventRightMouseUp, self._cx, self._cy)
        return None

    # -- scroll handling -------------------------------------------------

    def _handle_scroll(self, gesture: GestureData):
        """Two-finger vertical scroll."""
        idx_y = gesture.landmarks[8].y
        mid_y = gesture.landmarks[12].y
        avg_y = (idx_y + mid_y) / 2.0

        if self._last_scroll_y is not None:
            dy = (self._last_scroll_y - avg_y) * 100  # scale to scroll units
            if int(dy) != 0:
                pyautogui.scroll(int(dy))

        self._last_scroll_y = avg_y
        direction = "▲" if self._last_scroll_y is None or avg_y < 0.5 else "▼"
        return {"text": f"Scroll {direction}", "level": None}

    # -- Spaces handling -------------------------------------------------

    def _handle_spaces(self, gesture: GestureData):
        """Open palm + swipe direction for Spaces / Mission Control."""
        now = time.time()
        if now - self._swipe_cooldown < 0.8:
            return {"text": "", "level": None}

        wrist_y = gesture.landmarks[0].y
        wrist_x = gesture.landmarks[0].x

        if wrist_y < 0.3:
            pyautogui.hotkey("ctrl", "up")       # Mission Control
            self._swipe_cooldown = now
            return {"text": "Mission Control", "level": 80}
        elif wrist_y > 0.7:
            pyautogui.hotkey("fn", "f11")        # Show Desktop
            self._swipe_cooldown = now
            return {"text": "Show Desktop", "level": 80}
        elif wrist_x < 0.3:
            pyautogui.hotkey("ctrl", "left")     # Previous Space
            self._swipe_cooldown = now
            return {"text": "← Space", "level": 80}
        elif wrist_x > 0.7:
            pyautogui.hotkey("ctrl", "right")    # Next Space
            self._swipe_cooldown = now
            return {"text": "Space →", "level": 80}

        return {"text": "", "level": None}

    # -- coordinate mapping ----------------------------------------------

    def _to_screen(self, nx, ny):
        span = 1.0 - 2.0 * self._margin
        fx = max(0.0, min(1.0, (nx - self._margin) / span))
        fy = max(0.0, min(1.0, (ny - self._margin) / span))
        return fx * self._sw, fy * self._sh

    # -- mouse event posting ---------------------------------------------

    _BUTTON_MAP = {
        # Values set at class level so they're resolved once at import time.
    }

    def _post_mouse(self, event_type, x, y):
        button = self._BUTTON_MAP.get(event_type, Quartz.kCGMouseButtonLeft)
        event = Quartz.CGEventCreateMouseEvent(None, event_type, (x, y), button)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


# Fill button map AFTER Quartz import succeeds (module level).
CursorMode._BUTTON_MAP = {
    Quartz.kCGEventLeftMouseDown:    Quartz.kCGMouseButtonLeft,
    Quartz.kCGEventLeftMouseUp:      Quartz.kCGMouseButtonLeft,
    Quartz.kCGEventLeftMouseDragged: Quartz.kCGMouseButtonLeft,
    Quartz.kCGEventRightMouseDown:   Quartz.kCGMouseButtonRight,
    Quartz.kCGEventRightMouseUp:     Quartz.kCGMouseButtonRight,
    Quartz.kCGEventRightMouseDragged: Quartz.kCGMouseButtonRight,
    Quartz.kCGEventMouseMoved:       Quartz.kCGMouseButtonLeft,
}
