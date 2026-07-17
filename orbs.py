# orbs.py -- Ethereal breathing orb with 5 animation states for GestureControl HUD.
"""
Self-contained module providing OrbLayer, a CALayer-hosted ethereal orb
with five animation states: IDLE, LISTENING, THINKING, SPEAKING, ERROR.

Usage:
    from Foundation import NSMakeRect
    from orbs import OrbLayer, OrbState

    orb = OrbLayer(frame=NSMakeRect(0, 0, 80, 80))
    orb.transition_to(OrbState.LISTENING)
    hud_view.addSublayer_(orb.layer)
"""

from enum import Enum

from Quartz import (
    CABasicAnimation,
    CAAnimationGroup,
    CACurrentMediaTime,
    CAKeyframeAnimation,
    CALayer,
    CAMediaTimingFunction,
    CAShapeLayer,
    CATransform3DIdentity,
    CGBitmapContextCreate,
    CGBitmapContextCreateImage,
    CGColorCreateGenericRGB,
    CGColorSpaceCreateDeviceRGB,
    CGContextClearRect,
    CGContextDrawRadialGradient,
    CGGradientCreateWithColors,
    CGPathCreateWithEllipseInRect,
    CGPointMake,
    CGRectMake,
    kCGImageAlphaPremultipliedFirst,
    kCGBitmapByteOrder32Big,
)

from Foundation import NSMakeRect


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class OrbState(Enum):
    """The five animation states of the orb."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Color palettes (from research document)
# ---------------------------------------------------------------------------

_STATE_COLORS = {
    OrbState.IDLE: ("#8D9FFF", "#BC82F3"),         # blue-purple
    OrbState.LISTENING: ("#4FC3F7", "#29B6F6"),     # cyan
    OrbState.THINKING: ("#BC82F3", "#FF6778"),      # purple-pink
    OrbState.SPEAKING: ("#66BB6A", "#FFBA71"),       # green-gold
    OrbState.ERROR: ("#FF5252", "#FF8A65"),          # red-orange
}


def hex_to_rgb(hex_str: str) -> tuple:
    """Convert a hex color string (e.g. '#8D9FFF') to (r,g,b) in 0.0-1.0."""
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16) / 255.0,
            int(h[2:4], 16) / 255.0,
            int(h[4:6], 16) / 255.0)


# ---------------------------------------------------------------------------
# OrbLayer
# ---------------------------------------------------------------------------

class OrbLayer:
    """A CALayer-hosted ethereal orb with 5 animation states.

    The orb is rendered once as a CGImage (radial gradient with off-center
    highlight for a 3D appearance) and set as CALayer.contents.  All motion
    (scale, opacity, rotation, position) is handled by CoreAnimation on the
    GPU -- the CGImage is only re-rendered on state transitions and during
    slow hue drift.

    Parameters
    ----------
    frame : CGRect
        The frame rect for the root layer, e.g. ``NSMakeRect(0,0,80,80)``.
    """

    def __init__(self, frame):
        self._frame = frame
        self._state = OrbState.IDLE
        self._width = frame.size.width
        self._height = frame.size.height
        self._radius = min(self._width, self._height) / 2.0
        self._hue_phase = 0.0         # 0.0-1.0, interpolates between the two state colours
        self._time_since_redraw = 0.0
        self._tick_count = 0

        # Build the full CALayer hierarchy and start in IDLE.
        self._build_layer_tree()
        self._render_orb()
        self._start_idle()

    # -- public API ----------------------------------------------------------

    @property
    def layer(self):
        """The root CALayer -- add this to your view's layer tree."""
        return self._root_layer

    @property
    def state(self) -> OrbState:
        """Current animation state."""
        return self._state

    def transition_to(self, state: OrbState) -> None:
        """Transition to a new state, tearing down old animations and
        building the set appropriate for *state*."""
        if not isinstance(state, OrbState):
            raise TypeError(
                f"Expected OrbState, got {type(state).__name__}"
            )

        self._teardown_animations()
        self._hide_all_state_layers()
        self._state = state
        self._hue_phase = 0.0
        self._time_since_redraw = 0.0
        self._render_orb()

        dispatcher = {
            OrbState.IDLE: self._start_idle,
            OrbState.LISTENING: self._start_listening,
            OrbState.THINKING: self._start_thinking,
            OrbState.SPEAKING: self._start_speaking,
            OrbState.ERROR: self._start_error,
        }
        dispatcher[state]()

    def tick(self, dt: float) -> None:
        """Call once per frame.  Drives hue-drift redraws and particle
        burst timing.  *dt* is the elapsed time in seconds since the
        previous call."""
        self._time_since_redraw += dt

        if self._state == OrbState.IDLE:
            if self._time_since_redraw >= 1.0:
                self._hue_phase = (self._hue_phase + 0.05) % 1.0
                self._render_orb()
                self._time_since_redraw = 0.0

        elif self._state == OrbState.THINKING:
            if self._time_since_redraw >= 0.5:
                self._hue_phase = (self._hue_phase + 0.15) % 1.0
                self._render_orb()
                self._time_since_redraw = 0.0

        elif self._state == OrbState.SPEAKING:
            self._tick_count += 1
            if self._tick_count % 18 == 0:          # ~ every 0.3 s at 60 fps
                self._burst_particles()

    # -- layer tree construction --------------------------------------------

    def _build_layer_tree(self) -> None:
        """Create the full CALayer hierarchy once."""
        w, h = self._width, self._height

        # ---- root layer ----------------------------------------------------
        root = CALayer.layer()
        root.setFrame_(self._frame)
        root.setMasksToBounds_(False)
        self._root_layer = root

        # ---- glow layer (behind orb, larger, lower opacity) ----------------
        glow_sz = w * 1.6
        glow_layer = CALayer.layer()
        glow_layer.setFrame_(NSMakeRect(
            (w - glow_sz) / 2, (h - glow_sz) / 2, glow_sz, glow_sz))
        glow_layer.setOpacity_(0.3)
        glow_layer.setCornerRadius_(glow_sz / 2)
        glow_layer.setMasksToBounds_(True)
        root.addSublayer_(glow_layer)
        self._glow_layer = glow_layer

        # ---- orb content layer (the main sphere) ---------------------------
        orb_layer = CALayer.layer()
        orb_layer.setFrame_(NSMakeRect(0, 0, w, h))
        orb_layer.setCornerRadius_(self._radius)
        orb_layer.setMasksToBounds_(True)
        root.addSublayer_(orb_layer)
        self._orb_layer = orb_layer

        # ---- ripple pool (listening) ---------------------------------------
        self._ripple_layers = []
        for _ in range(4):
            ripple = CAShapeLayer.layer()
            ripple.setFrame_(NSMakeRect(0, 0, w, h))
            ripple.setPath_(CGPathCreateWithEllipseInRect(
                NSMakeRect(0, 0, w, h), None))
            ripple.setFillColor_(None)
            ripple.setLineWidth_(1.5)
            ripple.setOpacity_(0.0)
            ripple.setHidden_(True)
            root.addSublayer_(ripple)
            self._ripple_layers.append(ripple)

        # ---- swirl circles (thinking, masked to orb) -----------------------
        self._swirl_layers = []
        swirl_hues = [
            (1.0, 0.5, 0.6),   # pink
            (0.5, 0.75, 1.0),  # cyan
            (1.0, 0.8, 0.4),   # gold
        ]
        for r_c, g_c, b_c in swirl_hues:
            swirl = CALayer.layer()
            sw_sz = self._radius * 0.65
            swirl.setFrame_(NSMakeRect(
                self._radius - sw_sz / 2,
                self._radius - sw_sz / 2,
                sw_sz, sw_sz))
            swirl.setCornerRadius_(sw_sz / 2)
            swirl.setMasksToBounds_(False)
            swirl.setBackgroundColor_(
                CGColorCreateGenericRGB(r_c, g_c, b_c, 0.5))
            swirl.setOpacity_(0.6)
            swirl.setHidden_(True)
            orb_layer.addSublayer_(swirl)
            self._swirl_layers.append(swirl)

        # ---- particle dots (speaking) --------------------------------------
        self._particle_layers = []
        dot_sz = 4.0
        for _ in range(12):
            dot = CALayer.layer()
            dot.setFrame_(NSMakeRect(
                self._radius - dot_sz / 2,
                self._radius - dot_sz / 2,
                dot_sz, dot_sz))
            dot.setCornerRadius_(dot_sz / 2)
            dot.setOpacity_(0.0)
            dot.setHidden_(True)
            root.addSublayer_(dot)
            self._particle_layers.append(dot)

    # -- orb rendering -------------------------------------------------------

    def _render_orb(self) -> None:
        """Render the orb as a CGImage (radial gradient) and apply to both
        the orb content layer and the glow layer."""
        w_i, h_i = int(self._width), int(self._height)
        glow_sz = int(self._radius * 1.6 * 2)

        c1_hex, c2_hex = _STATE_COLORS[self._state]
        r1, g1, b1 = hex_to_rgb(c1_hex)
        r2, g2, b2 = hex_to_rgb(c2_hex)

        t = self._hue_phase
        r = r1 + (r2 - r1) * t
        g = g1 + (g2 - g1) * t
        b = b1 + (b2 - b1) * t

        cs = CGColorSpaceCreateDeviceRGB()

        # -- orb image ---------------------------------------------------
        ctx = CGBitmapContextCreate(
            None,
            w_i, h_i, 8, 0, cs,
            kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Big,
        )
        CGContextClearRect(ctx, CGRectMake(0, 0, w_i, h_i))

        white = CGColorCreateGenericRGB(1.0, 1.0, 1.0, 1.0)
        base = CGColorCreateGenericRGB(r, g, b, 1.0)
        grad = CGGradientCreateWithColors(cs, [white, base], [0.0, 1.0])

        cx, cy = w_i / 2.0, h_i / 2.0
        rad = min(cx, cy)
        off = rad * 0.25
        CGContextDrawRadialGradient(
            ctx, grad,
            CGPointMake(cx - off, cy - off), 0.0,
            CGPointMake(cx, cy), rad * 1.05,
            0,
        )
        orb_img = CGBitmapContextCreateImage(ctx)
        self._orb_layer.setContents_(orb_img)

        # -- glow image -------------------------------------------------
        gctx = CGBitmapContextCreate(
            None,
            glow_sz, glow_sz, 8, 0, cs,
            kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Big,
        )
        CGContextClearRect(gctx, CGRectMake(0, 0, glow_sz, glow_sz))

        glow_inner = CGColorCreateGenericRGB(r, g, b, 0.7)
        glow_outer = CGColorCreateGenericRGB(r, g, b, 0.0)
        g_grad = CGGradientCreateWithColors(cs, [glow_inner, glow_outer], [0.0, 1.0])

        gcx, gcy = glow_sz / 2.0, glow_sz / 2.0
        grow = min(gcx, gcy)
        CGContextDrawRadialGradient(
            gctx, g_grad,
            CGPointMake(gcx, gcy), grow * 0.01,
            CGPointMake(gcx, gcy), grow,
            0,
        )
        glow_img = CGBitmapContextCreateImage(gctx)
        self._glow_layer.setContents_(glow_img)

    # -- animation helpers ---------------------------------------------------

    def _teardown_animations(self) -> None:
        """Remove every animation from every managed layer."""
        for layer in (
            [self._orb_layer, self._glow_layer]
            + self._ripple_layers
            + self._swirl_layers
            + self._particle_layers
        ):
            layer.removeAllAnimations()

    def _hide_all_state_layers(self) -> None:
        """Hide all state-specific sub-layers (ripples, swirl, particles)."""
        for ripple in self._ripple_layers:
            ripple.setHidden_(True)
            ripple.setOpacity_(0.0)
        for swirl in self._swirl_layers:
            swirl.setHidden_(True)
        for dot in self._particle_layers:
            dot.setHidden_(True)
            dot.setOpacity_(0.0)

    @staticmethod
    def _make_anim(key_path, from_val, to_val, duration,
                   autoreverse=True, timing="easeInEaseOut"):
        """Convenience: a repeating CABasicAnimation with autoreverse."""
        a = CABasicAnimation.animationWithKeyPath_(key_path)
        a.setFromValue_(from_val)
        a.setToValue_(to_val)
        a.setDuration_(duration)
        a.setAutoreverses_(autoreverse)
        a.setRepeatCount_(float("inf"))
        a.setTimingFunction_(CAMediaTimingFunction.functionWithName_(timing))
        return a

    # -- IDLE ----------------------------------------------------------------

    def _start_idle(self) -> None:
        """Gentle breathing pulse + opacity shimmer."""
        self._orb_layer.addAnimation_forKey_(
            self._make_anim("transform.scale", 0.95, 1.05, 4.0),
            "idle_pulse",
        )
        self._orb_layer.addAnimation_forKey_(
            self._make_anim("opacity", 0.85, 1.0, 6.0),
            "idle_shimmer",
        )
        self._glow_layer.addAnimation_forKey_(
            self._make_anim("opacity", 0.25, 0.40, 6.0),
            "idle_glow",
        )

    # -- LISTENING -----------------------------------------------------------

    def _start_listening(self) -> None:
        """Scale up, glow intensifies, ripple rings expand outward."""
        # scale up orb
        scale = CABasicAnimation.animationWithKeyPath_("transform.scale")
        scale.setFromValue_(1.0)
        scale.setToValue_(1.08)
        scale.setDuration_(0.3)
        scale.setTimingFunction_(
            CAMediaTimingFunction.functionWithName_("easeOut"))
        scale.setFillMode_("forwards")
        scale.setRemovedOnCompletion_(False)
        self._orb_layer.addAnimation_forKey_(scale, "listen_scale")

        # glow
        glow = CABasicAnimation.animationWithKeyPath_("opacity")
        glow.setFromValue_(0.3)
        glow.setToValue_(0.55)
        glow.setDuration_(0.3)
        glow.setFillMode_("forwards")
        glow.setRemovedOnCompletion_(False)
        self._glow_layer.addAnimation_forKey_(glow, "listen_glow")

        # ripples
        cyan_cg = CGColorCreateGenericRGB(
            0.31, 0.76, 0.97, 1.0)          # #4FC3F7
        for i, ripple in enumerate(self._ripple_layers):
            ripple.setHidden_(False)
            ripple.setStrokeColor_(cyan_cg)
            self._spawn_ripple(ripple, delay=i * 0.375)

    def _spawn_ripple(self, ripple, delay=0.0) -> None:
        """Animate a single ripple ring: expand + fade, loop forever."""
        ripple.setOpacity_(0.0)
        ripple.setTransform_(CATransform3DIdentity)

        scale = CABasicAnimation.animationWithKeyPath_("transform.scale")
        scale.setFromValue_(0.2)
        scale.setToValue_(2.0)
        scale.setDuration_(1.5)
        scale.setTimingFunction_(
            CAMediaTimingFunction.functionWithName_("easeOut"))

        fade = CABasicAnimation.animationWithKeyPath_("opacity")
        fade.setFromValue_(0.8)
        fade.setToValue_(0.0)
        fade.setDuration_(1.5)
        fade.setTimingFunction_(
            CAMediaTimingFunction.functionWithName_("easeOut"))

        group = CAAnimationGroup.animation()
        group.setAnimations_([scale, fade])
        group.setDuration_(1.5)
        group.setBeginTime_(CACurrentMediaTime() + delay)
        group.setRepeatCount_(float("inf"))

        ripple.addAnimation_forKey_(group, "ripple")

    # -- THINKING ------------------------------------------------------------

    def _start_thinking(self) -> None:
        """Faster pulse + internal swirl circles rotating at different
        speeds."""
        self._orb_layer.addAnimation_forKey_(
            self._make_anim("transform.scale", 0.92, 1.08, 2.0),
            "think_pulse",
        )
        self._glow_layer.addAnimation_forKey_(
            self._make_anim("opacity", 0.28, 0.48, 2.0),
            "think_glow",
        )

        import math
        speeds = (1.0, 1.7, 2.3)            # rad / s
        for i, swirl in enumerate(self._swirl_layers):
            swirl.setHidden_(False)
            full_circle = 2.0 * math.pi
            rot = CABasicAnimation.animationWithKeyPath_(
                "transform.rotation.z")
            rot.setFromValue_(0.0)
            rot.setToValue_(full_circle)
            rot.setDuration_(full_circle / speeds[i])
            rot.setRepeatCount_(float("inf"))
            rot.setTimingFunction_(
                CAMediaTimingFunction.functionWithName_("linear"))
            swirl.addAnimation_forKey_(rot, f"think_swirl_{i}")

    # -- SPEAKING ------------------------------------------------------------

    def _start_speaking(self) -> None:
        """Rapid scale pulse + glow expansion + particle bursts."""
        self._orb_layer.addAnimation_forKey_(
            self._make_anim("transform.scale", 1.0, 1.12, 0.3),
            "speak_pulse",
        )
        self._glow_layer.addAnimation_forKey_(
            self._make_anim("transform.scale", 1.0, 1.3, 0.3),
            "speak_glow_scale",
        )
        self._glow_layer.addAnimation_forKey_(
            self._make_anim("opacity", 0.3, 0.7, 0.3),
            "speak_glow_opacity",
        )
        self._burst_particles()

    def _burst_particles(self) -> None:
        """Fire a radial burst of dot particles from the orb centre."""
        import math, random

        color_hex = _STATE_COLORS[self._state][1]
        r_c, g_c, b_c = hex_to_rgb(color_hex)

        n = len(self._particle_layers)
        for i, dot in enumerate(self._particle_layers):
            dot.setHidden_(False)
            dot.setOpacity_(1.0)
            dot.setTransform_(CATransform3DIdentity)
            dot.setBackgroundColor_(
                CGColorCreateGenericRGB(r_c, g_c, b_c, 0.85))

            angle = (i / n) * 2.0 * math.pi
            distance = self._radius * (1.4 + random.random() * 0.6)
            dx = math.cos(angle) * distance
            dy = math.sin(angle) * distance

            pos = CABasicAnimation.animationWithKeyPath_("position")
            pos.setFromValue_((self._radius, self._radius))
            pos.setToValue_((self._radius + dx, self._radius + dy))
            pos.setDuration_(0.7)
            pos.setTimingFunction_(
                CAMediaTimingFunction.functionWithName_("easeOut"))

            fade = CABasicAnimation.animationWithKeyPath_("opacity")
            fade.setFromValue_(1.0)
            fade.setToValue_(0.0)
            fade.setDuration_(0.7)
            fade.setTimingFunction_(
                CAMediaTimingFunction.functionWithName_("easeOut"))

            group = CAAnimationGroup.animation()
            group.setAnimations_([pos, fade])
            group.setDuration_(0.7)

            dot.addAnimation_forKey_(group, f"particle_{i}")

    # -- ERROR ---------------------------------------------------------------

    def _start_error(self) -> None:
        """Contract -> flash -> settle -> shake via CAKeyframeAnimation."""
        scale_kf = CAKeyframeAnimation.animationWithKeyPath_(
            "transform.scale")
        scale_kf.setValues_([1.0, 0.7, 1.15, 0.95, 1.02, 1.0])
        scale_kf.setKeyTimes_([0.0, 0.1, 0.2, 0.35, 0.55, 0.8])
        scale_kf.setDuration_(2.0)
        scale_kf.setTimingFunction_(
            CAMediaTimingFunction.functionWithName_("easeInEaseOut"))
        self._orb_layer.addAnimation_forKey_(scale_kf, "error_scale")

        glow_kf = CAKeyframeAnimation.animationWithKeyPath_("opacity")
        glow_kf.setValues_([0.3, 0.3, 0.95, 0.3, 0.4, 0.3])
        glow_kf.setKeyTimes_([0.0, 0.09, 0.15, 0.3, 0.5, 0.8])
        glow_kf.setDuration_(2.0)
        self._glow_layer.addAnimation_forKey_(glow_kf, "error_glow")

        cx = self._width / 2.0
        shake = CAKeyframeAnimation.animationWithKeyPath_("position.x")
        shake.setValues_(
            [cx, cx, cx + 4, cx - 4, cx + 3, cx - 3,
             cx + 2, cx - 2, cx + 1, cx - 1, cx])
        shake.setKeyTimes_(
            [0.0, 0.2, 0.3, 0.4, 0.5, 0.55,
             0.6, 0.65, 0.7, 0.75, 0.85])
        shake.setDuration_(2.0)
        self._orb_layer.addAnimation_forKey_(shake, "error_shake")
