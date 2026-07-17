# hud.py
import warnings
import objc
from AppKit import (
    NSWindow, NSView, NSColor, NSScreen, NSBorderlessWindowMask,
    NSNonactivatingPanelMask, NSFloatingWindowLevel, NSBackingStoreBuffered,
    NSColorSpace, NSTextField, NSMakeRect,
)

# ---------------------------------------------------------------------------
# Graceful orb import -- the orbs module is built concurrently.
# If it is not available, orb features are disabled with a warning.
# ---------------------------------------------------------------------------
try:
    from orbs import OrbState, OrbLayer  # noqa: F401
    ORBS_AVAILABLE = True
except ImportError:
    ORBS_AVAILABLE = False
    OrbState = None   # type: ignore
    OrbLayer = None   # type: ignore


class HUD:
    """Transparent pill-shaped overlay for mode feedback.

    Extended with optional orb, transcription display, and voice status pill.
    All features gracefully degrade when dependencies are unavailable.
    """

    # Dimensions
    BASE_W, BASE_H = 200, 60
    WIDE_W = 280
    TRANSCRIPTION_H = 100
    ORB_H = 160
    ORB_TRANSCRIPTION_H = 200
    ORB_DIAMETER = 90

    def __init__(self):
        self._window = None
        self._label = None
        self._bar = None
        self._visible = False

        # Extended HUD elements
        self._transcription_label = None
        self._voice_status_label = None
        self._orb_layer = None
        self._orb_sublayer_added = False

        if not ORBS_AVAILABLE:
            warnings.warn("orbs module not found; orb features disabled")

    # ------------------------------------------------------------------
    # Public API (existing, preserved verbatim)
    # ------------------------------------------------------------------

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

    def close(self):
        if self._window:
            self._window.close()
            self._window = None
        self._label = None
        self._bar = None
        self._transcription_label = None
        self._voice_status_label = None
        self._orb_layer = None
        self._orb_sublayer_added = False

    # ------------------------------------------------------------------
    # Orb integration
    # ------------------------------------------------------------------

    def add_orb_layer(self, orb_layer):
        """Accept an externally-created OrbLayer and add it to the HUD overlay.

        This is the preferred path when the orb is created and managed
        by the main gesture-control loop (imports orbs itself).  The orb
        is added as a sublayer of the background view and the window
        layout is recalculated to fit it.

        Args:
            orb_layer: An OrbLayer instance (CALayer subclass).
        """
        if self._window is None:
            self._create_window()
        self._orb_layer = orb_layer
        bg = self._window.contentView()
        bg.layer().addSublayer_(orb_layer)
        self._orb_sublayer_added = True
        self._recalc_layout()

    def show_orb(self):
        """Show the ethereal orb above the text label.

        If the orbs module is not available, this is a no-op with a warning.
        The window expands to accommodate the orb.
        """
        if not ORBS_AVAILABLE:
            warnings.warn("Cannot show orb: orbs module not available")
            return
        if self._window is None:
            self._create_window()
        if self._orb_layer is None:
            orb_rect = NSMakeRect(0, 0, self.ORB_DIAMETER, self.ORB_DIAMETER)
            self._orb_layer = OrbLayer(orb_rect)
        if not self._orb_sublayer_added:
            bg = self._window.contentView()
            bg.layer().addSublayer_(self._orb_layer.layer)
            self._orb_sublayer_added = True
        self._recalc_layout()

    def hide_orb(self):
        """Hide the orb and shrink the window back."""
        if self._orb_layer is not None and self._orb_sublayer_added:
            self._orb_layer.layer.removeFromSuperlayer()
            self._orb_sublayer_added = False
        self._recalc_layout()

    def set_orb_state(self, state):
        """Set orb visual state.

        Args:
            state: OrbState enum value, or an int that maps to OrbState.
        """
        if not ORBS_AVAILABLE or self._orb_layer is None:
            return
        try:
            if isinstance(state, int):
                state = OrbState(state)
            self._orb_layer.transition_to(state)
        except (ValueError, TypeError):
            pass

    # ------------------------------------------------------------------
    # Transcription display
    # ------------------------------------------------------------------

    def show_transcription(self, text):
        """Show streaming transcription text below the mode name.

        Window height expands from 60px to 100px to accommodate.
        """
        if self._window is None:
            self._create_window()
        self._ensure_transcription_label()
        self._transcription_label.setStringValue_(text)
        self._recalc_layout()

    def clear_transcription(self):
        """Clear the transcription text and shrink window if needed."""
        if self._transcription_label is not None:
            self._transcription_label.setStringValue_("")
        self._recalc_layout()

    # ------------------------------------------------------------------
    # Voice status pill
    # ------------------------------------------------------------------

    def show_voice_status(self, status):
        """Show a small voice status badge next to the mode name.

        Typical values: '🎤 Listening...', 'Thinking...', 'Sent ✅'.
        """
        if self._window is None:
            self._create_window()
        self._ensure_voice_status_label()
        self._voice_status_label.setStringValue_(status)
        self._recalc_layout()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_window(self):
        """Create the floating HUD window shell and base views.

        Actual sizing and layout is deferred to _recalc_layout()
        so the window dimensions reflect what is currently visible.
        """
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        width, height = self.BASE_W, self.BASE_H
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

        # Main mode label
        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 18, width - 20, 24))
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setBordered_(False)
        self._label.setDrawsBackground_(False)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setFont_(objc.lookUpClass("NSFont").systemFontOfSize_(18))
        self._label.setAlignment_(2)  # center
        bg.addSubview_(self._label)

    def _ensure_transcription_label(self):
        if self._transcription_label is not None:
            return
        w = self.BASE_W - 20
        lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 25, w, 22))
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        lbl.setBordered_(False)
        lbl.setDrawsBackground_(False)
        lbl.setTextColor_(NSColor.colorWithWhite_alpha_(1.0, 0.7))
        lbl.setFont_(objc.lookUpClass("NSFont").systemFontOfSize_(12))
        lbl.setAlignment_(2)  # center
        lbl.setLineBreakMode_(4)  # NSLineBreakByTruncatingTail
        bg = self._window.contentView()
        bg.addSubview_(lbl)
        self._transcription_label = lbl

    def _ensure_voice_status_label(self):
        if self._voice_status_label is not None:
            return
        lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(10, 18, 95, 22))
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        lbl.setBordered_(False)
        lbl.setDrawsBackground_(False)
        lbl.setTextColor_(NSColor.colorWithRed_green_blue_alpha_(0.3, 0.9, 0.3, 1.0))
        lbl.setFont_(objc.lookUpClass("NSFont").systemFontOfSize_(12))
        lbl.setAlignment_(0)  # left
        bg = self._window.contentView()
        bg.addSubview_(lbl)
        self._voice_status_label = lbl

    def _has_transcription(self):
        return (
            self._transcription_label is not None
            and bool(self._transcription_label.stringValue())
        )

    def _has_orb(self):
        return self._orb_sublayer_added and self._orb_layer is not None

    def _recalc_layout(self):
        """Recalculate window size and subview positions.

        Height rules (descending priority):
            orb + transcription  -> 200
            orb only              -> 160
            transcription only    -> 100
            neither               -> 60

        Width expands to 280 if orb or voice status is shown.
        """
        if self._window is None:
            return

        has_orb = self._has_orb()
        has_trans = self._has_transcription()
        has_voice = self._voice_status_label is not None

        # ---- width ----
        width = self.WIDE_W if (has_orb or has_voice) else self.BASE_W

        # ---- height + label baseline ----
        if has_orb and has_trans:
            height = self.ORB_TRANSCRIPTION_H   # 200
            label_y = 55
            trans_y = 25
            orb_y = height - self.ORB_DIAMETER - 20
        elif has_orb:
            height = self.ORB_H                 # 160
            label_y = 25
            trans_y = -5
            orb_y = height - self.ORB_DIAMETER - 10
        elif has_trans:
            height = self.TRANSCRIPTION_H       # 100
            label_y = 55
            trans_y = 25
            orb_y = -1
        else:
            height = self.BASE_H                # 60
            label_y = 18
            trans_y = -5
            orb_y = -1

        # ---- reposition window ----
        screen = NSScreen.mainScreen()
        screen_frame = screen.frame()
        x = (screen_frame.size.width - width) / 2
        y = screen_frame.size.height - height - 40
        new_frame = NSMakeRect(x, y, width, height)

        self._window.setFrame_display_animate_(new_frame, True, False)

        # Resize background view
        bg = self._window.contentView()
        bg.setFrame_(((0, 0), (width, height)))

        # ---- reposition label (right of voice status if voice shown) ----
        if has_voice:
            label_x = 108
            label_w = width - label_x - 10
            self._voice_status_label.setFrame_(NSMakeRect(10, label_y, 95, 22))
        else:
            label_x = 10
            label_w = width - 20

        if self._label:
            self._label.setFrame_(NSMakeRect(label_x, label_y, label_w, 24))

        # ---- reposition transcription label ----
        if self._transcription_label is not None:
            self._transcription_label.setFrame_(NSMakeRect(10, trans_y, width - 20, 22))

        # ---- reposition orb ----
        if has_orb and orb_y > 0:
            orb_x = (width - self.ORB_DIAMETER) / 2
            try:
                self._orb_layer.layer.setFrame_(
                    NSMakeRect(orb_x, orb_y, self.ORB_DIAMETER, self.ORB_DIAMETER)
                )
            except Exception:
                pass
