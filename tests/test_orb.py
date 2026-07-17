# test_orb.py -- Tests for orbs.py
import pytest
from orbs import OrbLayer, OrbState, hex_to_rgb


# ---------------------------------------------------------------------------
# OrbState
# ---------------------------------------------------------------------------

def test_orb_state_values():
    """OrbState has the five expected members with correct values."""
    assert OrbState.IDLE.value == "idle"
    assert OrbState.LISTENING.value == "listening"
    assert OrbState.THINKING.value == "thinking"
    assert OrbState.SPEAKING.value == "speaking"
    assert OrbState.ERROR.value == "error"


def test_orb_state_membership():
    """Every member is an instance of OrbState."""
    for s in OrbState:
        assert isinstance(s, OrbState)


# ---------------------------------------------------------------------------
# hex_to_rgb
# ---------------------------------------------------------------------------

def test_hex_to_rgb_valid():
    """hex_to_rgb converts hash-prefixed hex to float tuple."""
    assert hex_to_rgb("#8D9FFF") == (0x8D / 255, 0x9F / 255, 0xFF / 255)


def test_hex_to_rgb_no_hash():
    """hex_to_rgb handles missing '#'."""
    r, g, b = hex_to_rgb("8D9FFF")
    assert r == 0x8D / 255
    assert g == 0x9F / 255
    assert b == 0xFF / 255


def test_hex_to_rgb_black():
    assert hex_to_rgb("#000000") == (0.0, 0.0, 0.0)


def test_hex_to_rgb_white():
    assert hex_to_rgb("#FFFFFF") == (1.0, 1.0, 1.0)


# ---------------------------------------------------------------------------
# OrbLayer -- construction
# ---------------------------------------------------------------------------

@pytest.fixture
def orb():
    """Return a fresh OrbLayer at 80x80 (headless-safe, no NSApp needed)."""
    from Foundation import NSMakeRect
    return OrbLayer(frame=NSMakeRect(0, 0, 80, 80))


def test_orb_initial_state(orb):
    """A new OrbLayer starts in IDLE."""
    assert orb.state == OrbState.IDLE


def test_orb_has_root_layer(orb):
    """orb.layer returns a non-None CALayer."""
    assert orb.layer is not None


def test_orb_root_layer_frame(orb):
    """The root layer's frame matches what was passed in."""
    from Foundation import NSMakeRect
    frame = orb.layer.frame()
    expected = NSMakeRect(0, 0, 80, 80)
    # CGRect equality via approximate float compare
    assert abs(frame.origin.x - expected.origin.x) < 1e-6
    assert abs(frame.origin.y - expected.origin.y) < 1e-6
    assert abs(frame.size.width - expected.size.width) < 1e-6
    assert abs(frame.size.height - expected.size.height) < 1e-6


def test_orb_has_sublayers(orb):
    """The root layer has children (glow + orb + ripples + particles)."""
    sub = orb.layer.sublayers()
    assert sub is not None
    assert len(sub) >= 6   # glow + orb + 4 ripples


def test_orb_has_orb_content(orb):
    """The orb content layer has rendered CGImage contents."""
    # The orb content layer is the second sublayer (glow is first).
    sub = orb.layer.sublayers()
    orb_content = sub[1]
    assert orb_content.contents() is not None


# ---------------------------------------------------------------------------
# OrbLayer -- state transitions
# ---------------------------------------------------------------------------

def test_transition_to_valid_states(orb):
    """transition_to() accepts every OrbState without raising."""
    for state in OrbState:
        orb.transition_to(state)
        assert orb.state == state


def test_transition_to_invalid_raises(orb):
    """transition_to() raises TypeError for non-OrbState values."""
    with pytest.raises(TypeError):
        orb.transition_to("idle")
    with pytest.raises(TypeError):
        orb.transition_to(None)
    with pytest.raises(TypeError):
        orb.transition_to(42)


def test_transition_does_not_crash_on_rapid_cycling(orb):
    """Rapid state transitions through all states do not raise."""
    for _ in range(10):
        for state in OrbState:
            orb.transition_to(state)


def test_transition_tears_down_old_animations(orb):
    """After transition_to, the orb layer has new animation keys."""
    orb.transition_to(OrbState.IDLE)
    keys_after_idle = set(orb._orb_layer.animationKeys() or [])
    assert len(keys_after_idle) >= 2  # idle_pulse + idle_shimmer

    orb.transition_to(OrbState.LISTENING)
    keys_after_listen = set(orb._orb_layer.animationKeys() or [])
    # Should have different set of keys
    assert "listen_scale" in keys_after_listen
    assert "idle_pulse" not in keys_after_listen


# ---------------------------------------------------------------------------
# OrbLayer -- state-specific animations
# ---------------------------------------------------------------------------

def test_idle_has_animations(orb):
    orb.transition_to(OrbState.IDLE)
    keys = set(orb._orb_layer.animationKeys() or [])
    assert "idle_pulse" in keys
    assert "idle_shimmer" in keys


def test_listening_has_animations(orb):
    orb.transition_to(OrbState.LISTENING)
    keys = set(orb._orb_layer.animationKeys() or [])
    assert "listen_scale" in keys


def test_thinking_has_animations(orb):
    orb.transition_to(OrbState.THINKING)
    keys = set(orb._orb_layer.animationKeys() or [])
    assert "think_pulse" in keys


def test_speaking_has_animations(orb):
    orb.transition_to(OrbState.SPEAKING)
    keys = set(orb._orb_layer.animationKeys() or [])
    assert "speak_pulse" in keys


def test_error_has_animations(orb):
    orb.transition_to(OrbState.ERROR)
    keys = set(orb._orb_layer.animationKeys() or [])
    assert "error_scale" in keys
    assert "error_shake" in keys


# ---------------------------------------------------------------------------
# OrbLayer -- tick
# ---------------------------------------------------------------------------

def test_tick_does_not_crash(orb):
    """tick() never raises regardless of state."""
    for state in OrbState:
        orb.transition_to(state)
        for _ in range(50):
            orb.tick(0.016)  # ~60 fps


def test_tick_accumulates_hue_phase(orb):
    """tick() advances _hue_phase over time in IDLE."""
    orb.transition_to(OrbState.IDLE)
    initial_phase = orb._hue_phase
    for _ in range(100):
        orb.tick(0.016)
    assert orb._hue_phase != initial_phase


def test_tick_accumulates_hue_phase_thinking(orb):
    """tick() also advances in THINKING (faster redraw cycle)."""
    orb.transition_to(OrbState.THINKING)
    initial_phase = orb._hue_phase
    for _ in range(50):
        orb.tick(0.016)
    assert orb._hue_phase != initial_phase


def test_tick_idle_resets_redraw_timer(orb):
    """After enough ticks, _time_since_redraw resets in IDLE."""
    orb.transition_to(OrbState.IDLE)
    orb.tick(1.5)
    assert orb._time_since_redraw < 1.0  # should have reset


def test_tick_speaking_increments_tick_count(orb):
    """Speaking state increments _tick_count."""
    orb.transition_to(OrbState.SPEAKING)
    assert orb._tick_count == 0
    for _ in range(30):
        orb.tick(0.016)
    assert orb._tick_count > 0


# ---------------------------------------------------------------------------
# OrbLayer -- edge cases
# ---------------------------------------------------------------------------

def test_orb_with_non_square_frame():
    """OrbLayer handles rectangular frame (non-square)."""
    from Foundation import NSMakeRect
    o = OrbLayer(frame=NSMakeRect(0, 0, 100, 60))
    assert o.state == OrbState.IDLE
    assert o._radius == 30.0  # min(100,60)/2


def test_orb_contents_present_after_multiple_transitions(orb):
    """Orb content is still set after rapid cycling."""
    for state in OrbState:
        orb.transition_to(state)
    sub = orb.layer.sublayers()
    orb_content_layer = sub[1]
    assert orb_content_layer.contents() is not None
