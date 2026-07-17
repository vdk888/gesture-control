# hud.py
import warnings
import objc
from AppKit import (
    NSWindow, NSView, NSColor, NSScreen, NSBorderlessWindowMask,
    NSNonactivatingPanelMask, NSFloatingWindowLevel, NSBackingStoreBuffered,
    NSColorSpace, NSTextField, NSMakeRect,
)

class HUD:
    """Transparent pill-shaped overlay for mode feedback."""

    def __init__(self):
        self._window = None
        self._label = None
        self._bar = None
        self._visible = False

    def show(self, text="", level=None, duration=None):
        """Show HUD with optional level bar. Auto-hides after duration seconds."""
        if self._window is None:
            self._create_window()

        if text:
            self._label.setStringValue_(text)
        else:
            self._label.setStringValue_("")

        self._window.orderFront_(None)
        self._visible = True

    def hide(self):
        if self._window:
            self._window.orderOut_(None)
        self._visible = False

    def _create_window(self):
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        width, height = 200, 60
        x = (screen_frame.size.width - width) / 2
        y = screen_frame.size.height - height - 40

        rect = NSMakeRect(x, y, width, height)
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSBorderlessWindowMask | NSNonactivatingPanelMask,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setLevel_(NSFloatingWindowLevel + 1)
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(True)
        self._window.setHasShadow_(True)

        # Pill background view
        bg = NSView.alloc().initWithFrame_(((0, 0), (width, height)))
        bg.setWantsLayer_(True)
        bg.layer().setCornerRadius_(20)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", objc.ObjCPointerWarning)
            bg.layer().setBackgroundColor_(
                NSColor.colorWithWhite_alpha_(0.0, 0.75).CGColor()
            )
        self._window.setContentView_(bg)

        # Label
        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 18, width - 20, 24))
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setBordered_(False)
        self._label.setDrawsBackground_(False)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFont_(objc.lookUpClass("NSFont").systemFontOfSize_(18))
        self._label.setAlignment_(2)  # center
        bg.addSubview_(self._label)

    def close(self):
        if self._window:
            self._window.close()
            self._window = None
