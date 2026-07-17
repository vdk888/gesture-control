#!/usr/bin/env python3
# demo_orb.py -- Standalone window showing the orb cycling through all 5 states.
"""
Opens a transparent floating window at the centre of the main screen
displaying an ethereal breathing orb.  The orb cycles through every
OrbState (IDLE -> LISTENING -> THINKING -> SPEAKING -> ERROR) spending
~4 seconds in each.

Press Esc or close the window to quit.
"""

import objc
import warnings

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBorderlessWindowMask,
    NSColor,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSNonactivatingPanelMask,
    NSScreen,
    NSTimer,
    NSView,
    NSWindow,
)
from Foundation import NSObject, NSRunLoop, NSDefaultRunLoopMode, NSDate

from orbs import OrbLayer, OrbState


# ---------------------------------------------------------------------------
# Orb window helper
# ---------------------------------------------------------------------------

class OrbWindow:
    """Creates a transparent borderless window hosting the orb layer."""

    def __init__(self, orb_size=120):
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        w = h = orb_size
        pad = 20
        x = (screen_frame.size.width - w) / 2
        y = (screen_frame.size.height - h) / 2

        rect = NSMakeRect(x - pad, y - pad, w + pad * 2, h + pad * 2)

        style = NSBorderlessWindowMask | NSNonactivatingPanelMask
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False,
        )
        self._window.setLevel_(NSFloatingWindowLevel + 1)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(True)
        self._window.setHasShadow_(False)

        # Layer-backed content view
        view = NSView.alloc().initWithFrame_(
            ((0, 0), (w + pad * 2, h + pad * 2)),
        )
        view.setWantsLayer_(True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", objc.ObjCPointerWarning)
            view.layer().setBackgroundColor_(
                NSColor.colorWithWhite_alpha_(0.0, 0.0).CGColor(),
            )

        self._view = view
        self._window.setContentView_(view)

    def add_orb_layer(self, orb_layer):
        """Add *orb_layer* to the content view's layer tree."""
        self._view.layer().addSublayer_(orb_layer)

    def show(self):
        self._window.orderFront_(None)

    def close(self):
        self._window.close()


# ---------------------------------------------------------------------------
# Main demo
# ---------------------------------------------------------------------------

_STATE_CYCLE = [
    OrbState.IDLE,
    OrbState.LISTENING,
    OrbState.THINKING,
    OrbState.SPEAKING,
    OrbState.ERROR,
]


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    # Create orb (centered in the transparent window)
    orb = OrbLayer(frame=NSMakeRect(20, 20, 120, 120))
    window = OrbWindow(orb_size=120)
    window.add_orb_layer(orb.layer)
    window.show()

    # State-cycling timer: advances to the next state every 4 seconds.
    state_index = 0
    elapsed = 0.0

    def cycle_state(_timer):
        nonlocal state_index, elapsed
        elapsed += 0.05                         # 50 ms tick
        orb.tick(0.05)

        # Advance every ~4 s
        if elapsed >= 4.0:
            elapsed = 0.0
            state_index = (state_index + 1) % len(_STATE_CYCLE)
            orb.transition_to(_STATE_CYCLE[state_index])

    # NSTimer at ~20 fps (fine for the demo's tick) -- fires on main run-loop.
    timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.05,
        _cycle_state,
        None,
        True,
    )
    NSRunLoop.mainRunLoop().addTimer_forMode_(timer, NSDefaultRunLoopMode)

    # Keep the app alive until the window is closed.
    app.activateIgnoringOtherApps_(True)

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        window.close()


if __name__ == "__main__":
    main()
