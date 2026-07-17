import math
import Quartz
from modes.base import Mode, GestureData
from filters import OneEuroFilter


class MouseMode(Mode):
    name = "Mouse"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        smooth = config["cursor_smooth"]
        self._filter_x = OneEuroFilter(freq=60, fc_min=smooth["fc_min"], beta=smooth["beta"])
        self._filter_y = OneEuroFilter(freq=60, fc_min=smooth["fc_min"], beta=smooth["beta"])
        self._cx = None
        self._cy = None
        self._pinching = False
        self._margin = config["margin"]
        self._pinch_on = config["pinch_on"]
        self._pinch_off = config["pinch_off"]
        self._sw = None
        self._sh = None

    def enter(self):
        super().enter()
        self._cx = None
        self._cy = None

    def update(self, gesture: GestureData):
        if gesture.landmarks is None:
            if self._pinching:
                self._pinching = False
                if self._cx is not None:
                    self._post_mouse(Quartz.kCGEventLeftMouseUp, self._cx, self._cy)
            return None

        if self._sw is None:
            bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
            self._sw = float(bounds.size.width)
            self._sh = float(bounds.size.height)

        lm = gesture.landmarks
        tip = lm[8]
        tx, ty = self._to_screen(tip.x, tip.y)

        if self._cx is None:
            self._cx, self._cy = tx, ty
            self._filter_x.filter(tx, gesture.timestamp)
            self._filter_y.filter(ty, gesture.timestamp)
        else:
            self._cx = self._filter_x.filter(tx, gesture.timestamp)
            self._cy = self._filter_y.filter(ty, gesture.timestamp)

        # Pinch detection
        from hand_tracking import _dist
        palm = _dist(lm[5], lm[17]) or 1e-6
        ratio = _dist(lm[4], lm[8]) / palm

        if not self._pinching and ratio < self._pinch_on:
            self._pinching = True
            self._post_mouse(Quartz.kCGEventLeftMouseDown, self._cx, self._cy)
        elif self._pinching and ratio > self._pinch_off:
            self._pinching = False
            self._post_mouse(Quartz.kCGEventLeftMouseUp, self._cx, self._cy)
        else:
            moved = (Quartz.kCGEventLeftMouseDragged if self._pinching
                     else Quartz.kCGEventMouseMoved)
            self._post_mouse(moved, self._cx, self._cy)

        return {"text": "Click" if self._pinching else "", "level": None}

    def _to_screen(self, nx, ny):
        span = 1.0 - 2.0 * self._margin
        fx = max(0.0, min(1.0, (nx - self._margin) / span))
        fy = max(0.0, min(1.0, (ny - self._margin) / span))
        return fx * self._sw, fy * self._sh

    def _post_mouse(self, event_type, x, y):
        event = Quartz.CGEventCreateMouseEvent(None, event_type, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
