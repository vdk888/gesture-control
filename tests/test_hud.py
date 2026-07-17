# test_hud.py
import pytest
from hud import HUD


def test_hud_init_state():
    """HUD initializes with None window/label and not visible."""
    h = HUD()
    assert h._window is None
    assert h._label is None
    assert h._visible is False
    assert h._bar is None


def test_hud_show_creates_window_lazily():
    """show() creates the NSWindow on first call."""
    h = HUD()
    assert h._window is None
    h.show("Test")
    assert h._window is not None
    assert h._visible is True
    h.close()


def test_hud_show_sets_label_text():
    """show() sets the NSTextField string value."""
    h = HUD()
    h.show("Gesture: Scroll")
    assert h._label.stringValue() == "Gesture: Scroll"
    h.close()


def test_hud_show_empty_text():
    """show() with empty text sets empty label."""
    h = HUD()
    h.show("")
    assert h._label.stringValue() == ""
    h.close()


def test_hud_hide():
    """hide() sets visible to False."""
    h = HUD()
    h.show("Test")
    assert h._visible is True
    h.hide()
    assert h._visible is False
    h.close()


def test_hud_close():
    """close() destroys the window and resets attributes."""
    h = HUD()
    h.show("Test")
    assert h._window is not None
    h.close()
    assert h._window is None


def test_hud_show_without_text_clears_label():
    """show() with no text argument clears the label."""
    h = HUD()
    h.show("First")
    assert h._label.stringValue() == "First"
    h.show()  # no text
    assert h._label.stringValue() == ""
    h.close()
