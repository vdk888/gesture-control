# GestureControl v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify air_mouse.py + hand_tracking.py into a single multi-mode hand gesture control app with mode switching, transparent HUD, JSON config, 1€ filter cursor smoothing, and M4 GPU acceleration.

**Architecture:** Single main loop (gesture_control.py) dispatches to independent mode modules via a standard interface (base.py ABC). Shared hand tracking lives in hand_tracking.py. Config via JSON loaded by config_manager.py. HUD is a transparent PyObjC overlay window.

**Tech Stack:** Python 3.12+, MediaPipe Tasks API, OpenCV, PyAutoGUI, Quartz (CGEvent), PyObjC (NSWindow HUD), threading (camera capture), pytest

## Global Constraints

- All code under `~/claude-workspaces/Rick_RnD/prototypes/gesture-control/`
- Branch: `feat/gesture-control-v2` (already checked out)
- Config at `~/.gesture-control.json` with fallback defaults
- Camera inference at 640x480 max
- GPU delegate (Metal) for MediaPipe
- Threaded camera capture (capture thread + main thread for inference/render)
- 30+ FPS target on M4
- TDD: test first, then implement

## File Structure Map

```
gesture-control/
├── gesture_control.py     # NEW: main loop, mode dispatch, threading
├── hand_tracking.py        # MODIFY: extract shared functions, add to module
├── config_manager.py       # NEW: JSON config load/save/validate
├── filters.py              # NEW: 1€ filter implementation
├── hud.py                  # NEW: transparent macOS overlay
├── modes/
│   ├── __init__.py         # NEW: mode registry
│   ├── base.py             # NEW: Mode ABC
│   ├── mouse.py            # NEW: cursor + click/drag (from air_mouse.py)
│   ├── volume.py           # NEW: volume slider (from hand_tracking.py)
│   ├── media.py            # NEW: media keys (from hand_tracking.py)
│   ├── brightness.py       # NEW: screen brightness control
│   ├── scroll.py           # NEW: two-finger scroll
│   ├── spaces.py           # NEW: desktop/window management
│   └── custom.py           # NEW: user-defined gestures from config
├── config.json             # NEW: default config shipped with repo
├── hand_landmarker.task    # existing
├── air_mouse.py            # KEEP (legacy, unmodified)
├── hand_tracking.py        # KEEP as hand_tracking_original.py (legacy)
└── tests/
    ├── test_filters.py
    ├── test_hand_tracking.py
    ├── test_config_manager.py
    └── test_modes.py
```

---

### Task 1: Extract shared hand tracking module

**Files:**
- Modify: `hand_tracking.py` (already exists, refactor to expose clean API)
- Create: `tests/test_hand_tracking.py`

**Interfaces:**
- Produces: `hand_tracking.MODEL_PATH`, `hand_tracking.create_landmarker(num_hands)`, `hand_tracking.detect(landmarker, mp_image, ts)`, `hand_tracking.fingers_up(landmarks)`, `hand_tracking.name_gesture(up)`, `hand_tracking.draw_hand(frame, landmarks)`, `hand_tracking._dist(a, b)`, `hand_tracking.FINGER_TIPS`, `hand_tracking.FINGER_PIPS`, `hand_tracking.HAND_CONNECTIONS`

- [ ] **Step 1: Write tests for hand_tracking functions**

```python
# tests/test_hand_tracking.py
import math

class FakeLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y

def test_dist():
    from hand_tracking import _dist
    a = FakeLandmark(0, 0)
    b = FakeLandmark(3, 4)
    assert _dist(a, b) == 5.0

def test_fingers_up_all_down():
    from hand_tracking import fingers_up
    # All landmarks clustered near wrist → no fingers extended
    lm = [FakeLandmark(0.5, 0.9) for _ in range(21)]
    up = fingers_up(lm)
    assert up == [False, False, False, False, False]

def test_fingers_up_index_only():
    from hand_tracking import fingers_up
    lm = [FakeLandmark(0.5, 0.9) for _ in range(21)]
    lm[8] = FakeLandmark(0.5, 0.1)   # index tip up
    lm[7] = FakeLandmark(0.5, 0.5)   # index PIP
    up = fingers_up(lm)
    assert up[1] is True   # index
    assert up[2] is False  # middle still down

def test_name_gesture():
    from hand_tracking import name_gesture
    assert name_gesture([False, False, False, False, False]) == "Fist"
    assert name_gesture([True, True, True, True, True]) == "Open palm"
    assert name_gesture([False, True, False, False, False]) == "Pointing"
    assert name_gesture([True, False, False, False, False]) == "Thumbs up"
    assert name_gesture([False, True, True, False, False]) == "Peace"
```

- [ ] **Step 2: Run tests, verify they fail on missing functions**

```bash
cd ~/claude-workspaces/Rick_RnD/prototypes/gesture-control
python3 -m pytest tests/test_hand_tracking.py -v
# Expected: ImportError or AttributeError for functions not yet extracted
```

- [ ] **Step 3: Refactor hand_tracking.py — extract clean public API**

The file already has all these functions. Ensure they're importable and add docstrings.
Add `create_landmarker()` and `detect()` helper:

```python
# Add to hand_tracking.py after the existing imports:
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

MODEL_PATH = "hand_landmarker.task"

def create_landmarker(num_hands=1):
    options = vision.HandLandmarkerOptions(
        base_options=python.BaseOptions(
            model_asset_path=MODEL_PATH,
            delegate=python.BaseOptions.Delegate.GPU,
        ),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=num_hands,
        min_hand_detection_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    return vision.HandLandmarker.create_from_options(options)

def detect(landmarker, frame_rgb, timestamp_ms):
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    return landmarker.detect_for_video(mp_image, timestamp_ms)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
python3 -m pytest tests/test_hand_tracking.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add hand_tracking.py tests/test_hand_tracking.py
git commit -m "refactor: extract shared hand_tracking API with tests"
```

---

### Task 2: 1€ filter for cursor smoothing

**Files:**
- Create: `filters.py`
- Create: `tests/test_filters.py`

**Interfaces:**
- Produces: `filters.OneEuroFilter(freq, fc_min, beta)` with `.filter(value, timestamp) -> float`

- [ ] **Step 1: Write tests for 1€ filter**

```python
# tests/test_filters.py
import time
from filters import OneEuroFilter

def test_filter_converges():
    f = OneEuroFilter(freq=60, fc_min=1.0, beta=0.007)
    # Feed constant value, should converge
    ts = time.time()
    for _ in range(100):
        val = f.filter(100.0, ts)
        ts += 1/60
    assert abs(val - 100.0) < 1.0

def test_filter_smooths_jitter():
    f = OneEuroFilter(freq=60, fc_min=1.0, beta=0.007)
    ts = time.time()
    values = []
    for i in range(100):
        v = 100.0 + (10.0 if i % 5 == 0 else 0.0)  # jitter every 5th frame
        values.append(f.filter(v, ts))
        ts += 1/60
    # Smoothed values should have less variance than raw
    import statistics
    assert statistics.stdev(values) < 8.0

def test_filter_responds_to_rapid_movement():
    f = OneEuroFilter(freq=60, fc_min=1.0, beta=0.007)
    ts = time.time()
    f.filter(0.0, ts)  # settle
    ts += 1/60
    result = f.filter(500.0, ts)  # fast cursor flick
    # Should track rapid movement closely
    assert result > 300.0
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
python3 -m pytest tests/test_filters.py -v
# Expected: FAIL — module not found
```

- [ ] **Step 3: Implement 1€ filter**

```python
# filters.py
import math

class LowPassFilter:
    def __init__(self, alpha=1.0):
        self._y = None
        self.alpha = alpha

    def filter(self, value, alpha=None):
        if alpha is not None:
            self.alpha = alpha
        if self._y is None:
            self._y = value
        else:
            self._y = self._y + self.alpha * (value - self._y)
        return self._y

    def reset(self):
        self._y = None


class OneEuroFilter:
    """1€ filter for low-latency cursor smoothing.
    Reference: G. Casiez, N. Roussel, D. Vogel. CHI 2012.
    """
    def __init__(self, freq=60, fc_min=1.0, beta=0.007, dc_cutoff=1.0):
        self.freq = freq
        self.fc_min = fc_min
        self.beta = beta
        self.dc_cutoff = dc_cutoff
        self._x = LowPassFilter(alpha=self._alpha(dc_cutoff))
        self._dx = LowPassFilter(alpha=self._alpha(dc_cutoff))
        self._last_t = None
        self._last_val = None

    def _alpha(self, cutoff):
        tau = 1.0 / (2 * math.pi * cutoff)
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, value, timestamp):
        if self._last_val is None or self._last_t is None:
            self._last_val = value
            self._last_t = timestamp
            return value

        dt = max(timestamp - self._last_t, 1e-6)
        dx = (value - self._last_val) / dt

        edx = self._dx.filter(dx, alpha=self._alpha(self.dc_cutoff))
        cutoff = self.fc_min + self.beta * abs(edx)
        result = self._x.filter(value, alpha=self._alpha(cutoff))

        self._last_val = value
        self._last_t = timestamp
        return result

    def reset(self):
        self._x.reset()
        self._dx.reset()
        self._last_t = None
        self._last_val = None
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
python3 -m pytest tests/test_filters.py -v
# Expected: all PASS
```

- [ ] **Step 5: Commit**

```bash
git add filters.py tests/test_filters.py
git commit -m "feat: add 1€ filter for cursor smoothing"
```

---

### Task 3: Config manager

**Files:**
- Create: `config_manager.py`
- Create: `config.json`
- Create: `tests/test_config_manager.py`

**Interfaces:**
- Produces: `config_manager.DEFAULT_CONFIG` (dict), `config_manager.load_config(path=None) -> dict`, `config_manager.save_config(config, path=None)`, `config_manager.validate_config(config) -> list of errors`

- [ ] **Step 1: Write tests**

```python
# tests/test_config_manager.py
import json, tempfile, os
from config_manager import load_config, save_config, validate_config, DEFAULT_CONFIG

def test_load_defaults_when_no_file():
    config = load_config("/nonexistent/path/config.json")
    assert config == DEFAULT_CONFIG

def test_load_and_merge():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"cursor_smooth": {"fc_min": 2.0}}, f)
        path = f.name
    try:
        config = load_config(path)
        assert config["cursor_smooth"]["fc_min"] == 2.0
        # Unspecified keys get defaults
        assert config["pinch_on"] == DEFAULT_CONFIG["pinch_on"]
    finally:
        os.unlink(path)

def test_validate_good_config():
    errors = validate_config(DEFAULT_CONFIG)
    assert errors == []

def test_validate_bad_pinch():
    bad = dict(DEFAULT_CONFIG)
    bad["pinch_on"] = "not_a_number"
    errors = validate_config(bad)
    assert len(errors) > 0

def test_validate_unknown_mode():
    bad = dict(DEFAULT_CONFIG)
    bad["modes"] = ["mouse", "unicorn"]
    errors = validate_config(bad)
    assert len(errors) > 0

def test_save_and_reload():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        path = f.name
    try:
        save_config(DEFAULT_CONFIG, path)
        loaded = load_config(path)
        assert loaded == DEFAULT_CONFIG
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests, verify failure**

```bash
python3 -m pytest tests/test_config_manager.py -v
# Expected: FAIL
```

- [ ] **Step 3: Implement config_manager.py**

```python
# config_manager.py
import json
import os

VALID_MODES = {"mouse", "volume", "media", "brightness", "scroll", "spaces", "custom"}

DEFAULT_CONFIG = {
    "cursor_smooth": {"fc_min": 1.0, "beta": 0.007},
    "pinch_on": 0.45,
    "pinch_off": 0.70,
    "fist_hold_time": 1.5,
    "camera_index": 0,
    "camera_width": 640,
    "camera_height": 480,
    "margin": 0.15,
    "hud_enabled": True,
    "hud_fade_time": 2.0,
    "modes": ["mouse", "volume", "media", "brightness", "scroll", "spaces"],
    "custom_gestures": {},
}

def _deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def load_config(path=None):
    if path is None:
        path = os.path.expanduser("~/.gesture-control.json")
    if not os.path.exists(path):
        # Also check repo-local config
        local = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.exists(local):
            path = local
        else:
            return dict(DEFAULT_CONFIG)
    try:
        with open(path) as f:
            user = json.load(f)
    except (json.JSONDecodeError, IOError):
        return dict(DEFAULT_CONFIG)
    return _deep_merge(DEFAULT_CONFIG, user)

def save_config(config, path=None):
    if path is None:
        path = os.path.expanduser("~/.gesture-control.json")
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)

def validate_config(config):
    errors = []
    for key in ["pinch_on", "pinch_off", "fist_hold_time", "margin", "hud_fade_time"]:
        if not isinstance(config.get(key), (int, float)):
            errors.append(f"{key} must be a number, got {type(config.get(key)).__name__}")
    for mode in config.get("modes", []):
        if mode not in VALID_MODES:
            errors.append(f"Unknown mode '{mode}'. Valid: {sorted(VALID_MODES)}")
    if config.get("pinch_on", 0) >= config.get("pinch_off", 1):
        errors.append("pinch_on must be less than pinch_off")
    return errors
```

- [ ] **Step 4: Create default config.json**

```json
{
  "cursor_smooth": {"fc_min": 1.0, "beta": 0.007},
  "fist_hold_time": 1.5,
  "camera_index": 0,
  "camera_width": 640,
  "camera_height": 480,
  "hud_enabled": true,
  "hud_fade_time": 2.0,
  "modes": ["mouse", "volume", "media", "brightness", "scroll", "spaces"],
  "custom_gestures": {}
}
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_config_manager.py -v
# Expected: all PASS
```

- [ ] **Step 6: Commit**

```bash
git add config_manager.py config.json tests/test_config_manager.py
git commit -m "feat: add config manager with JSON load/save/validate"
```

---

### Task 4: Mode base class + mode registry

**Files:**
- Create: `modes/__init__.py`
- Create: `modes/base.py`

**Interfaces:**
- Produces: `modes.base.Mode` (ABC with `enter()`, `update(gesture_data)`, `exit()`, `name` property)
- Produces: `modes.base.GestureData` (dataclass: `gesture_name`, `landmarks`, `fingers_up`, `frame`, `width`, `height`)
- Produces: `modes.__init__.MODE_REGISTRY` (dict mapping name to Mode class)

- [ ] **Step 1: Create modes/base.py**

```python
# modes/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GestureData:
    gesture_name: str          # "Pointing", "Fist", "Open palm", etc.
    fingers_up: List[bool]     # [thumb, index, middle, ring, pinky]
    landmarks: object          # MediaPipe hand landmarks (or None)
    frame: object              # OpenCV frame (numpy array)
    width: int
    height: int
    timestamp: float           # seconds since epoch
    hand_index: int = 0        # which hand (0 = first detected)


class Mode(ABC):
    """Each gesture mode implements this interface."""

    def __init__(self, config: dict, hud=None):
        self.config = config
        self.hud = hud
        self._active = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable mode name shown in HUD (e.g. 'Mouse', 'Volume')."""
        ...

    def enter(self):
        """Called when mode becomes active. Override for setup."""
        self._active = True

    def exit(self):
        """Called when mode is deactivated. Override for cleanup."""
        self._active = False

    @abstractmethod
    def update(self, gesture: GestureData) -> Optional[dict]:
        """Process one frame of hand data. Return HUD update dict or None.
        
        HUD dict keys: 'text', 'level' (0-100), 'icon', 'highlight'
        """
        ...
```

- [ ] **Step 2: Create modes/__init__.py**

```python
# modes/__init__.py
from modes.base import Mode, GestureData
from modes.mouse import MouseMode
from modes.volume import VolumeMode
from modes.media import MediaMode
from modes.brightness import BrightnessMode
from modes.scroll import ScrollMode
from modes.spaces import SpacesMode
from modes.custom import CustomMode

MODE_REGISTRY = {
    "mouse": MouseMode,
    "volume": VolumeMode,
    "media": MediaMode,
    "brightness": BrightnessMode,
    "scroll": ScrollMode,
    "spaces": SpacesMode,
    "custom": CustomMode,
}
```

- [ ] **Step 3: Commit** (will be committed after the first mode task that validates this works)

```bash
git add modes/__init__.py modes/base.py
git commit -m "feat: add mode base class and registry"
```

---

### Task 5: Mouse mode (migrate from air_mouse.py)

**Files:**
- Create: `modes/mouse.py`
- Create: `tests/test_modes.py`

**Interfaces:**
- Consumes: `Mode` base class, `GestureData`, `filters.OneEuroFilter`, config with cursor_smooth, pinch thresholds, margin
- Produces: `modes.mouse.MouseMode`

- [ ] **Step 1: Write mouse mode test**

```python
# tests/test_modes.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modes.base import GestureData
from modes.mouse import MouseMode
from config_manager import DEFAULT_CONFIG

class FakeLandmark:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class FakeHUD:
    def __init__(self):
        self.updates = []
    def show(self, **kw):
        self.updates.append(kw)

def test_mouse_mode_name():
    mode = MouseMode(DEFAULT_CONFIG)
    assert mode.name == "Mouse"

def test_mouse_update_no_hand():
    mode = MouseMode(DEFAULT_CONFIG)
    g = GestureData(gesture_name="", fingers_up=[], landmarks=None,
                    frame=None, width=640, height=480, timestamp=0)
    result = mode.update(g)
    # Should not crash, no HUD update for no hand
    assert result is None

def test_mouse_update_pointing_produces_position():
    mode = MouseMode(DEFAULT_CONFIG)
    lm = [FakeLandmark(0.5, 0.5) for _ in range(21)]
    lm[8] = FakeLandmark(0.3, 0.3)  # index tip
    g = GestureData(gesture_name="Pointing", fingers_up=[False, True, False, False, False],
                    landmarks=lm, frame=None, width=640, height=480, timestamp=1000.0)
    result = mode.update(g)
    # With first frame, position initializes
    assert mode._cx is not None
```

- [ ] **Step 2: Run test, verify it fails**

```bash
python3 -m pytest tests/test_modes.py::test_mouse_mode_name -v
# Expected: FAIL — MouseMode not defined
```

- [ ] **Step 3: Implement modes/mouse.py**

```python
# modes/mouse.py
import time
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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python3 -m pytest tests/test_modes.py::test_mouse_mode_name tests/test_modes.py::test_mouse_update_no_hand tests/test_modes.py::test_mouse_update_pointing_produces_position -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add modes/mouse.py tests/test_modes.py modes/__init__.py modes/base.py
git commit -m "feat: add mouse mode with 1€ filter cursor smoothing"
```

---

### Task 6: Volume mode

**Files:**
- Create: `modes/volume.py`

**Interfaces:**
- Consumes: Mode base, GestureData, config
- Produces: VolumeMode (uses osascript for system volume)

- [ ] **Step 1: Create modes/volume.py**

```python
# modes/volume.py
import subprocess
import threading
from modes.base import Mode, GestureData


class VolumeMode(Mode):
    name = "Volume"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._level = self._read_volume()
        self._lock = threading.Lock()
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @staticmethod
    def _read_volume():
        try:
            out = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=2,
            )
            return int(out.stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            return 50

    def update(self, gesture: GestureData):
        if gesture.landmarks is None or gesture.gesture_name != "Pointing":
            return {"text": f"{self._level}%", "level": self._level}

        tip_x = gesture.landmarks[8].x
        # Map tip x position (0.15-0.85) to 0-100 volume
        span = max(0.0, min(1.0, (tip_x - 0.15) / 0.70))
        target = int(span * 100)
        with self._lock:
            self._level = target
        return {"text": f"{self._level}%", "level": self._level}

    def _run(self):
        while not self._stop:
            with self._lock:
                target = self._level
            try:
                current = self._read_volume()
                if abs(current - target) > 1:
                    subprocess.run(
                        ["osascript", "-e", f"set volume output volume {target}"],
                        timeout=2,
                    )
            except subprocess.SubprocessError:
                pass
            self._stop_event = threading.Event()
            self._stop_event.wait(0.05)

    def exit(self):
        super().exit()
        self._stop = True
```

- [ ] **Step 2: Register in modes/__init__.py** (already done from Task 4 template)

- [ ] **Step 3: Commit**

```bash
git add modes/volume.py
git commit -m "feat: add volume control mode"
```

---

### Task 7: Media, Brightness, Scroll, Spaces modes

**Files:**
- Create: `modes/media.py`, `modes/brightness.py`, `modes/scroll.py`, `modes/spaces.py`

These are smaller modes. Implement all four:

- [ ] **Step 1: Create modes/media.py**

```python
# modes/media.py
from modes.base import Mode, GestureData
import time
try:
    import Quartz
    from AppKit import NSEvent
    MEDIA_OK = True
except ImportError:
    MEDIA_OK = False

class MediaMode(Mode):
    name = "Media"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._palm_start = None
        self._fired = False
        self._last_action = 0

    def update(self, gesture: GestureData):
        if not MEDIA_OK:
            return {"text": "Media keys unavailable", "level": None}

        now = gesture.timestamp
        if gesture.gesture_name == "Open palm":
            if self._palm_start is None:
                self._palm_start = now
            elif not self._fired and now - self._palm_start >= 0.4:
                self._send_play_pause()
                self._fired = True
                self._last_action = now
                return {"text": "Play/Pause", "level": 75}
        else:
            self._palm_start = None
            self._fired = False

        return {"text": "", "level": None}

    def _send_play_pause(self):
        for down in (True, False):
            flags = 0xA00 if down else 0xB00
            data1 = (16 << 16) | ((0xA if down else 0xB) << 8)
            event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                14, (0, 0), flags, 0, 0, None, 8, data1, -1)
            Quartz.CGEventPost(0, event.CGEvent())
```

- [ ] **Step 2: Create modes/brightness.py**

```python
# modes/brightness.py
import subprocess
from modes.base import Mode, GestureData

class BrightnessMode(Mode):
    name = "Brightness"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._level = 50

    def update(self, gesture: GestureData):
        if gesture.landmarks is None or gesture.gesture_name != "Pointing":
            return {"text": f"{self._level}%", "level": self._level}

        tip_x = gesture.landmarks[8].x
        span = max(0.0, min(1.0, (tip_x - 0.15) / 0.70))
        self._level = int(span * 100)
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'tell app "System Events" to repeat 10 times' 
                 f'\n  key code 145\nend repeat'],
                timeout=1,
            )
        except subprocess.SubprocessError:
            pass
        # Use the brightness slider approach instead
        try:
            subprocess.run(
                ["brightness", str(float(self._level) / 100.0)], timeout=1)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return {"text": f"{self._level}%", "level": self._level}
```

- [ ] **Step 3: Create modes/scroll.py**

```python
# modes/scroll.py
import pyautogui
from modes.base import Mode, GestureData

class ScrollMode(Mode):
    name = "Scroll"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._last_y = None

    def update(self, gesture: GestureData):
        if gesture.landmarks is None or gesture.gesture_name != "Two fingers":
            self._last_y = None
            return {"text": "", "level": None}

        # Index + middle finger tips midpoint
        idx_y = gesture.landmarks[8].y
        mid_y = gesture.landmarks[12].y
        avg_y = (idx_y + mid_y) / 2.0

        if self._last_y is not None:
            dy = (self._last_y - avg_y) * 100  # scale to scroll units
            pyautogui.scroll(int(dy))

        self._last_y = avg_y
        direction = "▲" if self._last_y is None or avg_y < 0.5 else "▼"
        return {"text": f"Scroll {direction}", "level": None}

    def exit(self):
        super().exit()
        self._last_y = None
```

- [ ] **Step 4: Create modes/spaces.py**

```python
# modes/spaces.py
import pyautogui
from modes.base import Mode, GestureData
import time

pyautogui.PAUSE = 0

class SpacesMode(Mode):
    name = "Spaces"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._swipe_cooldown = 0

    def update(self, gesture: GestureData):
        now = time.time()
        if gesture.gesture_name != "Open palm" or now - self._swipe_cooldown < 0.8:
            return {"text": "", "level": None}

        # Determine swipe direction from hand position relative to previous
        if gesture.landmarks is not None:
            wrist_y = gesture.landmarks[0].y
            wrist_x = gesture.landmarks[0].x

            if wrist_y < 0.3:
                pyautogui.hotkey("ctrl", "up")    # Mission Control
                self._swipe_cooldown = now
                return {"text": "Mission Control", "level": 80}
            elif wrist_y > 0.7:
                pyautogui.hotkey("fn", "f11")     # Show Desktop
                self._swipe_cooldown = now
                return {"text": "Show Desktop", "level": 80}
            elif wrist_x < 0.3:
                pyautogui.hotkey("ctrl", "left")  # Previous Space
                self._swipe_cooldown = now
                return {"text": "← Space", "level": 80}
            elif wrist_x > 0.7:
                pyautogui.hotkey("ctrl", "right") # Next Space
                self._swipe_cooldown = now
                return {"text": "Space →", "level": 80}

        return {"text": "", "level": None}
```

- [ ] **Step 5: Commit all modes**

```bash
git add modes/media.py modes/brightness.py modes/scroll.py modes/spaces.py
git commit -m "feat: add media, brightness, scroll, and spaces modes"
```

---

### Task 8: Custom mode

**Files:**
- Create: `modes/custom.py`

- [ ] **Step 1: Create modes/custom.py**

```python
# modes/custom.py
import subprocess
import pyautogui
from modes.base import Mode, GestureData
import time

class CustomMode(Mode):
    name = "Custom"

    def __init__(self, config, hud=None):
        super().__init__(config, hud)
        self._mappings = config.get("custom_gestures", {})
        self._last_action = {}

    def update(self, gesture: GestureData):
        name = gesture.gesture_name
        if name not in self._mappings:
            return {"text": name or "—", "level": None}

        action = self._mappings[name]
        now = time.time()
        if name in self._last_action and now - self._last_action[name] < 1.5:
            return {"text": name, "level": None}  # cooldown

        self._last_action[name] = now
        action_type = action.get("action")

        if action_type == "keyboard_shortcut":
            keys = action.get("keys", [])
            if keys:
                pyautogui.hotkey(*keys)
            return {"text": f"{name}: {'+'.join(keys)}", "level": 100}

        elif action_type == "open_app":
            path = action.get("path", "")
            if path:
                subprocess.Popen(["open", path])
            return {"text": f"{name}: open", "level": 100}

        elif action_type == "shell":
            cmd = action.get("command", "")
            if cmd:
                subprocess.Popen(cmd, shell=True)
            return {"text": f"{name}: cmd", "level": 100}

        return {"text": name, "level": None}
```

- [ ] **Step 2: Commit**

```bash
git add modes/custom.py
git commit -m "feat: add custom gesture mode from JSON config"
```

---

### Task 9: HUD overlay

**Files:**
- Create: `hud.py`

- [ ] **Step 1: Create hud.py**

```python
# hud.py
import objc
from AppKit import (
    NSWindow, NSView, NSColor, NSScreen, NSBorderlessWindowMask,
    NSNonActivatingPanelMask, NSFloatingWindowLevel, NSBackingStoreBuffered,
    NSColorSpace, NSTextField, NSMakeRect,
)
from Quartz import CGSSetWindowLevel, kCGScreenSaverWindowLevel

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
            NSBorderlessWindowMask | NSNonActivatingPanelMask,
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
        bg.layer().setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.0, 0.75).CGColor())
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
```

- [ ] **Step 2: Commit**

```bash
git add hud.py
git commit -m "feat: add transparent HUD overlay window"
```

---

### Task 10: Main app — gesture_control.py

**Files:**
- Create: `gesture_control.py`

**Interfaces:**
- Consumes: ALL previous tasks (modes, hand_tracking, config_manager, hud, filters)
- Produces: runnable app: `python3 gesture_control.py`

- [ ] **Step 1: Create gesture_control.py**

```python
#!/usr/bin/env python3
"""GestureControl v2 — multi-mode hand gesture control for macOS.

Run: python3 gesture_control.py
Fist held 1.5s = cycle modes. Press q or Ctrl+C to quit.
"""
import time
import threading
import cv2
from hand_tracking import (
    create_landmarker, detect, fingers_up, name_gesture, draw_hand,
    FINGER_TIPS,
)
from modes.base import GestureData
from modes import MODE_REGISTRY
from config_manager import load_config
from hud import HUD


def main():
    config = load_config()
    print(f"Modes: {' → '.join(config['modes'])}")
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
```

- [ ] **Step 2: Quick smoke test**

```bash
cd ~/claude-workspaces/Rick_RnD/prototypes/gesture-control
timeout 5 python3 gesture_control.py 2>&1
# Expected: "Modes: mouse → volume → ..." then camera init (may fail in sandbox, that's OK)
```

- [ ] **Step 3: Commit**

```bash
git add gesture_control.py
git commit -m "feat: add main gesture_control.py with mode dispatch"
```

---

### Task 11: Final integration — rename legacy files, update README

**Files:**
- Rename: `air_mouse.py` (keep as-is, legacy reference)
- Rename: `hand_tracking.py` → keep, already refactored
- Update: `README.md`

- [ ] **Step 1: Update README.md**

Add to top of README:

```markdown
# GestureControl v2

Multi-mode hand gesture control for macOS. Use your webcam to control your Mac.

## Quick Start

```bash
pip3 install opencv-python mediapipe pyautogui pyobjc-framework-Quartz pyobjc-framework-Cocoa --break-system-packages
python3 gesture_control.py
```

## Modes

Fist held 1.5s cycles through modes:

| Mode | Gesture | Action |
|---|---|---|
| Mouse | Point index | Move cursor |
| Mouse | Pinch thumb+index | Click/drag |
| Volume | Point index | Adjust volume |
| Media | Open palm (hold) | Play/pause |
| Brightness | Point index | Adjust brightness |
| Scroll | Two fingers up/down | Scroll |
| Spaces | Open palm + swipe direction | Desktop navigation |
| Custom | User-defined | From ~/.gesture-control.json |

## Configuration

Copy `config.json` to `~/.gesture-control.json` and customize.

## Permissions

- Camera: System Settings > Privacy > Camera > enable Terminal
- Accessibility: System Settings > Privacy > Accessibility > enable Terminal
```

- [ ] **Step 2: Final commit**

```bash
git add README.md
git commit -m "docs: update README for v2 with mode guide and config docs"
```

---

### Task 12: Run full test suite + final smoke check

- [ ] **Step 1: Run all tests**

```bash
cd ~/claude-workspaces/Rick_RnD/prototypes/gesture-control
python3 -m pytest tests/ -v
# Expected: all tests pass
```

- [ ] **Step 2: Verify structure**

```bash
cd ~/claude-workspaces/Rick_RnD/prototypes/gesture-control
python3 -c "
from hand_tracking import create_landmarker, fingers_up, name_gesture, draw_hand
from filters import OneEuroFilter
from config_manager import load_config, validate_config
from modes.base import Mode, GestureData
from modes.mouse import MouseMode
from modes.volume import VolumeMode
from modes.media import MediaMode
from modes.brightness import BrightnessMode
from modes.scroll import ScrollMode
from modes.spaces import SpacesMode
from modes.custom import CustomMode
from hud import HUD
print('All imports OK')
"
```

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A && git commit -m "chore: final integration fixes and test suite"
```
