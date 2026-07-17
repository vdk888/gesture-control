# GestureControl v2 — Design Spec

**Date:** 2026-07-17
**Status:** Approved
**Author:** Rick (R&D) + Joris

## Overview

Unify and extend the existing gesture-control codebase into a single multi-mode macOS hand-gesture control app. Fist-hold to cycle through modes (Mouse, Volume, Media, Brightness, Scroll, Spaces, Custom), transparent HUD overlay, JSON config, M4-optimized performance.

## Architecture

Single main app that dispatches to mode modules. Each mode has a standard interface.

```
gesture-control/
├── gesture_control.py     # main loop, mode dispatch, config loading
├── hand_tracking.py        # shared: MediaPipe model, fingers_up(), name_gesture(), draw_hand()
├── hud.py                  # transparent macOS overlay (PyObjC NSWindow)
├── config_manager.py       # load/save/validate config.json
├── modes/
│   ├── __init__.py
│   ├── base.py             # Mode ABC: enter(), update(), exit()
│   ├── mouse.py            # cursor movement, click, drag, right-click
│   ├── volume.py           # volume slider
│   ├── media.py            # play/pause, next track, prev track
│   ├── brightness.py       # screen brightness
│   ├── scroll.py           # two-finger scroll
│   ├── spaces.py           # Mission Control, desktop left/right, Show Desktop
│   └── custom.py           # user-defined gestures from config
├── config.json             # user settings + custom gesture mappings
├── hand_landmarker.task    # MediaPipe model (existing)
└── requirements.txt
```

## Data Flow (per frame)

```
Webcam → OpenCV frame → flip → RGB conversion
    → mp.Image → HandLandmarker.detect_for_video()
    → hand_tracking.fingers_up(landmarks)
    → gesture_control dispatch to current mode
    → mode.update(gesture, frame, hud)
    → Quartz/PyAutoGUI/osascript output
    → HUD render + camera frame with overlays
```

## Mode Switching

- **Trigger:** Fist held for `fist_hold_time` seconds (default 1.5s)
- **Cycle order:** Mouse → Volume → Media → Brightness → Scroll → Spaces → Custom → loop
- **Feedback:** HUD shows mode name with slide animation; camera window shows mode label
- **Hysteresis:** once fist triggers a switch, fist must be released before next switch

## Modes

### Mouse
- Point index finger → cursor movement (1€ filter smoothing)
- Pinch thumb+index → left click (with hysteresis: PINCH_ON/PINCH_OFF)
- Pinch thumb+middle → right click
- Hold pinch + move → drag
- Cursor maps to screen with configurable margins

### Volume
- Point index finger → horizontal position maps to 0-100% volume
- Background thread applies via osascript (no blocking camera loop)
- HUD shows volume bar

### Media
- Open palm → play/pause (hold 0.4s)
- Swipe right → next track
- Swipe left → previous track
- Uses NSEvent media keys

### Brightness
- Point index finger → horizontal position maps to 0-100% brightness
- Uses CoreBrightness or osascript

### Scroll
- Two fingers extended (index+middle) → vertical position controls scroll speed
- Hand above midpoint = scroll up, below = scroll down
- PyAutoGUI scroll

### Spaces
- Open palm swipe left → previous Space (Ctrl+Left)
- Open palm swipe right → next Space (Ctrl+Right)
- Open palm swipe up → Mission Control (Ctrl+Up)
- Open palm swipe down → Show Desktop (F11)

### Custom
- User-defined in config.json
- Supported actions: keyboard shortcut, open app, shell command, AppleScript
- Gesture → action mapping in config

## HUD

Two rendering layers:

### Camera Window (existing, enhanced)
- Hand skeleton overlay with colored joints
- Mode name (top-left)
- Current gesture name (near hand)
- FPS counter
- Mode-specific indicators (volume bar, brightness bar, etc.)

### Transparent Overlay (new)
- Small pill-shaped window, top-center of screen
- Shows: mode icon + name, level/progress bar, brief gesture confirmation
- Fades out after 2s of inactivity
- Built with PyObjC: NSWindow with transparent background, NSView with CoreAnimation
- Non-interactive (clicks pass through)

## Cursor Smoothing

Replace exponential smoothing with 1€ filter:
- Two parameters: fc_min (cutoff for slow movements) and beta (speed coefficient)
- Adapts to movement speed: heavy smoothing when slow/precise, light smoothing when fast
- Standard in HCI research (Géry Casiez, CHI 2012)
- Tuned defaults: fc_min=1.0, beta=0.007, derived from user studies

## JSON Config

File: `~/.gesture-control.json` (or project-local `config.json`)

```json
{
  "cursor_smooth": {"fc_min": 1.0, "beta": 0.007},
  "pinch_on": 0.45,
  "pinch_off": 0.70,
  "fist_hold_time": 1.5,
  "camera_index": 0,
  "camera_width": 640,
  "camera_height": 480,
  "margin": 0.15,
  "hud_enabled": true,
  "hud_fade_time": 2.0,
  "modes": ["mouse", "volume", "media", "brightness", "scroll", "spaces", "custom"],
  "custom_gestures": {
    "peace": {
      "action": "keyboard_shortcut",
      "keys": ["cmd", "w"],
      "description": "Close window"
    },
    "thumbs_up": {
      "action": "open_app",
      "path": "/Applications/Safari.app",
      "description": "Open Safari"
    }
  }
}
```

## Error Handling

| Condition | Behavior |
|---|---|
| No camera found | Print error, show System Settings link, exit 1 |
| Accessibility denied | Detect via dummy CGEvent, show alert dialog |
| Model file missing | Check on startup, print download URL |
| Mode crashes | Catch exception, log traceback, fall back to previous mode |
| Invalid config JSON | Use defaults, print warning with parse error location |

## Performance (M4)

- Camera capture on **dedicated thread** (decoupled from inference + render)
- MediaPipe **GPU delegate** (Metal) via `base_options` configuration
- Inference at **640x480** (sufficient for hand tracking, 4x fewer pixels than 1080p)
- HUD renders via **CoreAnimation** layer-backed views (GPU compositing)
- Mode code runs synchronously after inference (no per-mode threads needed)
- Target: **30+ FPS** on M4, <10ms inference latency

## Testing

- `tests/` directory with pytest
- Unit tests for: fingers_up(), name_gesture(), config validation, mode switching logic
- Integration: mock camera frames via saved images, verify mode dispatch
- Manual smoke test checklist in README

## Migration from v1

- `air_mouse.py` → merged into `modes/mouse.py`
- `hand_tracking.py` → shared module, volume mode extracted to `modes/volume.py`
- Media keys code → `modes/media.py`
- Backward compat: `config.json` with defaults matching current behavior
