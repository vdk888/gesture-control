#!/usr/bin/env python3
"""GestureControl v2 -- multi-mode hand gesture control for macOS.

Run: python3 gesture_control.py
Fist held 1.5s = cycle Cursor <-> System.  3 fingers = voice send (anywhere).
Peace hold 1s = toggle voice always-on.  Press q or Ctrl+C to quit.
"""
import time
import cv2
from hand_tracking import (
    create_landmarker, detect, fingers_up, name_gesture, draw_hand,
)
from modes.base import GestureData
from modes import MODE_REGISTRY
from config_manager import load_config
from hud import HUD

# -- Orb integration (optional, fails gracefully if orbs.py not available) --
try:
    from orbs import OrbLayer, OrbState
except ImportError:
    OrbLayer = None  # type: ignore[assignment]
    OrbState = None

# -- Gesture cheat sheet per mode --------------------------------------------

CHEAT_SHEET = {
    "Cursor": [
        "Point -> move cursor",
        "Pinch thumb+index -> left click",
        "Pinch thumb+middle -> right click",
        "Two fingers -> scroll",
        "Open palm + swipe -> Spaces",
        "Fist hold -> System mode",
        "3 fingers -> Voice",
    ],
    "System": [
        "Point -> adjust volume",
        "Two fingers -> brightness",
        "Open palm hold -> play/pause",
        "Fist hold -> Cursor mode",
        "3 fingers -> Voice",
    ],
    # Backward-compat cheat sheets preserved for old modes
    "Mouse": [
        "Point -> move cursor",
        "Pinch thumb+index -> click",
        "Fist hold -> next mode",
        "3 fingers -> Voice send",
    ],
    "Volume": [
        "Point -> adjust volume",
        "Fist hold -> next mode",
        "3 fingers -> Voice send",
    ],
    "Media": [
        "Open palm hold -> play/pause",
        "Fist hold -> next mode",
        "3 fingers -> Voice send",
    ],
    "Brightness": [
        "Point -> adjust brightness",
        "Fist hold -> next mode",
        "3 fingers -> Voice send",
    ],
    "Scroll": [
        "Two fingers up/down -> scroll",
        "Fist hold -> next mode",
        "3 fingers -> Voice send",
    ],
    "Spaces": [
        "Open palm left/right -> switch desktop",
        "Open palm up -> Mission Control",
        "Open palm down -> Show Desktop",
        "Fist hold -> next mode",
        "3 fingers -> Voice send",
    ],
}


def _draw_cheat_sheet(frame, mode_name):
    """Draw semi-transparent gesture cheat sheet for current mode."""
    if mode_name not in CHEAT_SHEET:
        return
    h, w = frame.shape[:2]
    lines = CHEAT_SHEET[mode_name]

    # Semi-transparent background box (right side)
    box_w = 310
    box_h = 20 + len(lines) * 22
    x0, y0 = w - box_w - 10, 40
    x1, y1 = x0 + box_w, y0 + box_h
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

    # Title
    cv2.putText(frame, f"Gestures -- {mode_name}", (x0 + 10, y0 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 100), 1)
    # Lines
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (x0 + 10, y0 + 48 + i * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)


# -- Orb state helper --------------------------------------------------------

def _compute_orb_state(mode, gesture_name):
    """Determine orb visual state from current mode and gesture context."""
    if OrbState is None:
        return None
    if not gesture_name:
        return OrbState.IDLE
    # VoiceMode state attributes (set by the mode itself)
    if hasattr(mode, 'error') and getattr(mode, 'error'):
        return OrbState.ERROR
    if hasattr(mode, 'processing') and getattr(mode, 'processing'):
        return OrbState.THINKING
    if hasattr(mode, 'speaking') and getattr(mode, 'speaking'):
        return OrbState.SPEAKING
    if hasattr(mode, 'listening') and getattr(mode, 'listening'):
        return OrbState.LISTENING
    # Default: breathing idle
    return OrbState.IDLE


# -- Main --------------------------------------------------------------------

def main():
    config = load_config()

    # Build the cycle (only modes explicitly listed in config["modes"])
    cycle_order = [m for m in config["modes"] if m in MODE_REGISTRY]
    if not cycle_order:
        print("No valid modes configured. Add 'cursor' and 'system' to config.")
        return

    # Voice mode is always available for the 3-finger trigger, even if not
    # in the cycle.  Ensure it's loaded.
    voice_mode = None
    if "voice" in MODE_REGISTRY and MODE_REGISTRY["voice"] is not None:
        voice_mode = MODE_REGISTRY["voice"](config, None)

    print(f"Modes: {' <-> '.join(cycle_order)}")
    print("Fist held 1.5s = cycle modes.  3 fingers = voice (anywhere).  q = quit.")
    print("Needs: Camera + Accessibility permissions in System Settings.")

    cap = cv2.VideoCapture(config["camera_index"])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["camera_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["camera_height"])
    if not cap.isOpened():
        print("Could not open webcam.")
        print("System Settings > Privacy & Security > Camera > enable Terminal")
        return

    landmarker = create_landmarker(num_hands=1)
    hud = HUD()

    # Initialize cycle modes
    modes = {}
    for name in cycle_order:
        if name in MODE_REGISTRY and MODE_REGISTRY[name] is not None:
            modes[name] = MODE_REGISTRY[name](config, hud)

    # Give voice mode the HUD reference now that it exists.
    # Start the voice pipeline immediately (always-on listening).
    if voice_mode is not None:
        voice_mode.hud = hud
        voice_mode.enter()  # starts the voice pipeline, keeps running
        print("Voice pipeline started (always-on listening)")

    # -- Initialize orb (optional, fails gracefully if orbs.py unavailable) --
    orb = None
    if OrbLayer is not None:
        try:
            orb_size = 80
            orb_frame = ((0, 0), (orb_size, orb_size))
            orb = OrbLayer(orb_frame)
            hud.add_orb_layer(orb)
            hud.show(text="")  # Show HUD window immediately
            print("Orb initialized.")
        except Exception as e:
            print(f"Warning: Could not initialize orb: {e}")
            orb = None
    else:
        print("Note: orbs module not available, continuing without orb")

    mode_index = 0
    current_mode = modes[cycle_order[mode_index]]
    current_mode.enter()

    # -- Peace-sign toggle state (voice always-on) --
    peace_start = None
    peace_toggled = False

    # -- 3-finger voice send cooldown --
    voice_send_cooldown = 0.0

    fist_start = None
    fist_active = False
    fist_hold = config["fist_hold_time"]

    prev = time.time()
    last_ts = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ts = int(time.time() * 1000)
        last_ts = max(ts, last_ts + 1)
        now = time.time()

        result = detect(landmarker, rgb, last_ts)
        height, width = frame.shape[:2]

        gesture_name = ""
        landmarks = None
        fingers = [False] * 5

        if result.hand_landmarks:
            landmarks = result.hand_landmarks[0]
            draw_hand(frame, landmarks)
            fingers = fingers_up(landmarks)
            gesture_name = name_gesture(fingers)
            cv2.putText(frame, gesture_name, (20, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # ================================================================
        # 3-FINGER VOICE SEND (from anywhere, 2s cooldown)
        # ================================================================
        if gesture_name == "3 fingers" and voice_mode is not None:
            if now - voice_send_cooldown >= 2.0:
                ok_sent = voice_mode.trigger_send()
                if ok_sent:
                    voice_send_cooldown = now

        # ================================================================
        # PEACE SIGN HOLD -> toggle voice always-on
        # ================================================================
        if gesture_name == "Peace" and voice_mode is not None:
            if peace_start is None:
                peace_start = now
            elif now - peace_start >= 1.0 and not peace_toggled:
                voice_mode.toggle_always_on()
                peace_toggled = True
        else:
            peace_start = None
            peace_toggled = False

        # ================================================================
        # FIST CYCLE (cursor <-> system)
        # ================================================================
        if gesture_name == "Fist":
            if fist_start is None:
                fist_start = now
            elif now - fist_start >= fist_hold and not fist_active:
                current_mode.exit()
                mode_index = (mode_index + 1) % len(cycle_order)
                current_mode = modes[cycle_order[mode_index]]
                current_mode.enter()
                fist_active = True
                if hud:
                    hud.show(text=current_mode.name, level=100)
        else:
            fist_start = None
            fist_active = False

        # ================================================================
        # Build gesture data
        # ================================================================
        gd = GestureData(
            gesture_name=gesture_name, fingers_up=fingers,
            landmarks=landmarks, frame=frame,
            width=width, height=height, timestamp=now,
        )

        # Background: voice mode HUD streaming (partials via show_transcription)
        if voice_mode is not None:
            voice_mode.update(gd)

        # Foreground: cycle mode dispatch + HUD
        hud_data = current_mode.update(gd)
        if hud_data:
            hud.show(**hud_data)
        elif orb is not None and not hud._visible:
            hud.show(text="")

        # Update orb state (prefer voice mode attributes when available)
        if orb is not None:
            orb_state = OrbState.IDLE
            if gesture_name:
                if voice_mode is not None:
                    if getattr(voice_mode, 'error', None):
                        orb_state = OrbState.ERROR
                    elif getattr(voice_mode, 'processing', False):
                        orb_state = OrbState.THINKING
                    elif getattr(voice_mode, 'speaking', False):
                        orb_state = OrbState.SPEAKING
                    elif getattr(voice_mode, 'listening', False):
                        orb_state = OrbState.LISTENING
                if orb_state == OrbState.IDLE:
                    orb_state = _compute_orb_state(current_mode, gesture_name)
            if orb_state is not None:
                orb.transition_to(orb_state)
            orb.tick(time.time() - prev)

        # Camera overlays
        cv2.putText(frame, f"Mode: {current_mode.name}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        fps = 1.0 / max(now - prev, 1e-6)
        prev = now
        cv2.putText(frame, f"{fps:4.0f} FPS", (width - 80, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        hint = "fist 1.5s = cycle    3 fingers = voice send    q = quit"
        cv2.putText(frame, hint, (10, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 2)

        # Gesture cheat sheet
        _draw_cheat_sheet(frame, current_mode.name)

        cv2.imshow("Gesture Control", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    landmarker.close()
    if voice_mode is not None:
        voice_mode.exit()
    if hud:
        hud.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
