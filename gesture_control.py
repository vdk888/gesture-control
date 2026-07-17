#!/usr/bin/env python3
"""GestureControl v2 — multi-mode hand gesture control for macOS.

Run: python3 gesture_control.py
Fist held 1.5s = cycle modes. Press q or Ctrl+C to quit.
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


def main():
    config = load_config()
    print(f"Modes: {' -> '.join(config['modes'])}")
    print("Fist held 1.5s = next mode. q = quit.")
    print("Needs: Camera + Accessibility permissions in System Settings.")

    cap = cv2.VideoCapture(config["camera_index"])
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config["camera_width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config["camera_height"])
    if not cap.isOpened():
        print("Could not open webcam.")
        print("System Settings > Privacy & Security > Camera > enable Terminal")
        return

    landmarker = create_landmarker(num_hands=1)
    hud = HUD() if config.get("hud_enabled") else None

    # Initialize modes
    mode_names = config["modes"]
    modes = {}
    for name in mode_names:
        if name in MODE_REGISTRY:
            modes[name] = MODE_REGISTRY[name](config, hud)

    if not modes:
        print("No valid modes configured. Exiting.")
        cap.release()
        landmarker.close()
        return

    mode_order = list(modes.keys())
    current_idx = 0
    current_mode = modes[mode_order[current_idx]]
    current_mode.enter()

    # Mode switching state
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

        # Mode switching: fist detection
        if gesture_name == "Fist":
            if fist_start is None:
                fist_start = now
            elif now - fist_start >= fist_hold and not fist_active:
                current_mode.exit()
                current_idx = (current_idx + 1) % len(mode_order)
                current_mode = modes[mode_order[current_idx]]
                current_mode.enter()
                fist_active = True
                if hud:
                    hud.show(text=current_mode.name, level=100)
        else:
            fist_start = None
            fist_active = False

        # Dispatch to current mode
        gd = GestureData(
            gesture_name=gesture_name, fingers_up=fingers,
            landmarks=landmarks, frame=frame,
            width=width, height=height, timestamp=now,
        )
        hud_data = current_mode.update(gd)

        # Update HUD
        if hud and hud_data:
            hud.show(**hud_data)

        # Camera window overlays
        cv2.putText(frame, f"Mode: {current_mode.name}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        fps = 1.0 / max(now - prev, 1e-6)
        prev = now
        cv2.putText(frame, f"{fps:4.0f} FPS", (width - 80, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        cv2.putText(frame, "fist 1.5s = mode    q = quit", (10, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 2)

        cv2.imshow("Gesture Control", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    landmarker.close()
    if hud:
        hud.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
