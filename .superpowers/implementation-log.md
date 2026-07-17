# Gesture Control v2 -- Implementation Log

## Task 12: Ethereal Breathing Orb (2026-07-17)

**Files**: `orbs.py`, `demo_orb.py`, `tests/test_orb.py`

### Patterns
- `CGBitmapContextCreate` + `CGContextDrawRadialGradient` with off-center
  highlight (`start_center` shifted ~25% of radius toward top-left) creates a
  3D sphere look without any shader code. The rendered CGImage is cached as
  `CALayer.contents` -- only re-rendered on state transition or hue drift.
- All motion (scale, opacity, rotation, position) is handled by CoreAnimation
  on the GPU. `CABasicAnimation` for pulsing, `CAKeyframeAnimation` for
  complex sequences (error contract/flash/settle/shake), `CAAnimationGroup`
  for combined effects (ripple scale+fade, particle position+fade).
- Five state-specific layer trees: **IDLE** (scale pulse + opacity shimmer),
  **LISTENING** (scale up + CAShapeLayer ripple rings with staggered
  `beginTime`), **THINKING** (fast pulse + 3 rotating gradient circles at
  different angular speeds masked inside orb), **SPEAKING** (rapid pulse +
  12 dot CALayers bursting radially), **ERROR** (keyframe contract/flash/
  settle + horizontal shake).
- `tick(dt)` drives redraw-triggered hue drift (IDLE: every ~1s, THINKING:
  every ~0.5s) and particle burst timing (SPEAKING: every ~18 ticks).

### Gotchas
- `CALayer.setTransform_(None)` raises `TypeError: depythonifying struct, got
  no sequence` -- PyObjC cannot bridge Python None to `CATransform3D`. Use
  `CATransform3DIdentity` (imported from `Quartz`) to reset a transform.
- `CGImageCreate(ctx)` takes 11 arguments in PyObjC (unlike Swift/ObjC where
  it's a convenience initializer). Use `CGBitmapContextCreateImage(ctx)`
  instead.
- All CoreAnimation classes (`CABasicAnimation`, `CAKeyframeAnimation`,
  `CAShapeLayer`, `CALayer`, `CAMediaTimingFunction`, `CAAnimationGroup`,
  `CATransform3DIdentity`) live directly in the `Quartz` namespace, not in
  a `Quartz.CoreAnimation` submodule.

### Commands
```bash
# Run orb tests
python3 -m pytest tests/test_orb.py -v

# Import check
python3 -c "from orbs import OrbLayer, OrbState; print('OK')"

# Demo (requires display)
python3 demo_orb.py
```

## Task 11: Voice Pipeline + Screenshot Modules (2026-07-17)

**Files**: `voice/__init__.py`, `voice/pipeline.py`, `voice/screenshot.py`, `requirements.txt`

### Patterns
- VoicePipeline uses two threads: the PortAudio callback thread (fast, VAD-only) and
  the stream-loop thread (handles partial transcription + sleep). The callback never
  blocks on IO or model inference -- it only does VAD + buffer extension under a lock.
- The VAD class is copied verbatim from `audio-listener/listener.py`. It is the proven
  implementation with Silero ONNX primary and energy RMS fallback.
- `CGDisplayCreateImage` + `NSBitmapImageRep` gives a pure-PyObjC screenshot without
  any subprocess call. `NSBitmapImageRep.initWithCGImage_` bridges directly from the
  Quartz CGImage to an AppKit rep, then `representationUsingType_properties_` encodes
  to PNG bytes.
- faster-whisper `base` model transcribes in ~300ms on M4 -- fast enough for
  re-transcribing the growing buffer every 500ms during active speech.

### Gotchas
- `sounddevice.InputStream` callbacks run in a PortAudio-managed OS thread.
  Threading.Lock is mandatory for buffer access shared between the callback and
  the stream-loop thread.
- PyObjC's `NSBitmapImageRep.representationUsingType_properties_` returns an
  `NSData`, not Python bytes. Use `.writeToFile_atomically_()` to persist,
  or `.bytes()` to get a Python bytes object.
- `test_load_defaults_when_no_file` was already failing before this task --
  a prior commit added voice config to DEFAULT_CONFIG without updating the
  test assertion. Not fixed here (separate concern).
- The `modes/__init__.py` and `modes/voice.py` were pre-existing changes in
  the working tree (from a prior commit). Only `voice/*` and `requirements.txt`
  were staged for this task.

### Commands
```bash
# Syntax check
python3 -c "import ast; ast.parse(open('voice/pipeline.py').read()); print('OK')"

# Import check
python3 -c "from voice import VoicePipeline, capture_screenshot; print('OK')"

# Test screenshot (needs display)
python3 -c "from voice.screenshot import capture_screenshot; print(capture_screenshot())"

# Run all tests
python3 -m pytest tests/ -v
```

## Task 10: Main App Integration (2026-07-17)

**Files**: `gesture_control.py`, `tests/test_gesture_control.py`

### Patterns
- Module-level attribute assignment (`gesture_control.detect = ...`) persists between tests.
  Prefer `patch.object()` to auto-cleanup. When direct assignment is used, tests that need
  the real function must explicitly restore it.
- OpenCV functions require real numpy arrays, not MagicMock objects.

### Gotchas
- `time.time()` advances only microseconds between frames in tests. Mode-switching tests
  that rely on timing thresholds need mocked time with advancing timestamps.
- `make_fist_landmarks()` needed careful thumb positioning: the thumb is "up" when
  `_dist(tip, pinky_mcp) > _dist(pip, pinky_mcp)`. For a fist, the tip must be closer
  to pinky_mcp than the pip.
- The `patch("gesture_control.HUD")` in the `with` block is required for tests to
  capture HUD calls; without it the real AppKit-based HUD is used.

### Commands
```bash
# Run all tests
python3 -m pytest tests/ -v

# Run just gesture_control tests
python3 -m pytest tests/test_gesture_control.py -v

# Quick import check
python3 -c "import gesture_control; print('OK')"

# Syntax check
python3 -c "import ast; ast.parse(open('gesture_control.py').read()); print('OK')"
```
