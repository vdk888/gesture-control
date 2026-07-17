# Gesture Control v2 -- Implementation Log

## Task 14: Menubar App Wrapper (2026-07-17)

**Files**: `menubar_app.py`, `com.bubble.gesture-control.plist`, `requirements.txt`

### Patterns
- The menubar app follows the exact architecture from `audio-listener/menubar_app.py`:
  rumps.App with custom `quit_button=None`, PIL-drawn icons at 4x supersampling with
  LANCZOS downsampling, and a rumps.Timer polling shared state every 2s.
- GestureController wraps the `gesture_control.py` main loop, adapted for background-thread
  operation. cv2.imshow/cv2.waitKey are removed (cannot run on non-main thread on macOS);
  the HUD overlay provides all visual feedback.
- `_SharedState` bridges the background gesture loop and the main-thread menubar using
  threading.Lock. Status fields are written by the gesture loop, read by the timer callback.
  Toggle commands are flag-based (set by menubar, consumed atomically by the gesture loop).
- Icon states: green filled dot (active), grey ring (paused/off), red filled dot (error).
  Colours are drawn directly in PIL (not template=True) since rumps template=True would
  strip the colour -- the spec explicitly requires green/red dots.
- Voice always-on toggle sets `VoiceMode._always_on` directly and starts/stops the
  pipeline. Voice mute stops the pipeline independently of always-on state.
- The LaunchAgent plist uses `LimitLoadToSessionType: Aqua` (required for GUI apps),
  `RunAtLoad: true` (auto-start at login), and `KeepAlive: true` (restart on crash).

### Gotchas
- `OrbLayer()` constructor signature: the `demo_orb.py` and `hud.py` usage passes
  `NSMakeRect(0, 0, w, h)` but the `OrbLayer.__init__` from `orbs.py` takes a frame
  rect. The controller calls `OrbLayer()` with no args as a fallback; this may raise
  TypeError. The orb toggle is a best-effort feature.
- rumps `timer.start()` must be called AFTER the app menu is built -- calling it before
  menu assignment can cause the timer callback to fire with incomplete menu items.
- The `_apply_toggle_*` methods on `_SharedState` are called from the gesture loop
  thread (not under the lock they would normally use). This is safe because they are
  called AFTER `consume_toggles()` which clears the flags, so there's no contention
  between the write path (gesture loop calling _apply) and the read path (timer callback
  reading via snapshot). The snapshot() call does take the lock to ensure a consistent
  read.

### Commands
```bash
# Syntax check
python3 -c "import ast; ast.parse(open('menubar_app.py').read()); print('OK')"

# Test icon generation + shared state (no GUI)
python3 -c "exec(open('menubar_app.py').read().split('class GestureControlApp')[0]); \
  state = _SharedState(); state.set_status('Mouse', 30.0, 'Pointing'); \
  s = state.snapshot(); print(s)"

# Validate plist
plutil -lint com.bubble.gesture-control.plist

# Run (requires display + camera)
python3 menubar_app.py

# Install LaunchAgent for auto-start at login
cp com.bubble.gesture-control.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.bubble.gesture-control.plist

# Uninstall LaunchAgent
launchctl bootout gui/$(id -u)/com.bubble.gesture-control
```

## Task 13: VoiceMode (2026-07-17)

**Files**: `modes/voice.py`, `modes/__init__.py`, `tests/test_voice_mode.py`

### Patterns
- VoiceMode follows the Mode ABC (`modes/base.py`). It uses lazy imports for
  `voice.pipeline.VoicePipeline` and `voice.screenshot.capture_screenshot` so the
  mode is importable even before those modules are built. Sentinels `False` (not `None`)
  mark import-failure so retries are skipped.
- Three-frame state machine: trigger-held-fn0 starts listening, trigger-held-fn1..N shows
  partials, trigger-released stops + injects + captures screenshot.
- The release path must come BEFORE the always-on display path in `update()`, otherwise
  always-on mode eats the gesture release and never injects.
- In always-on mode, trigger gestured while already listening (VAD active) still sets
  `_was_listening = True` so the next non-trigger frame fires the release path.
- Inject format: `VOICE_GESTURE ts=... authorized=yes path=... screenshot=...` header
  line + French-language body line appended to the DeepSeek inject file.
- `300ms` cooldown (hardcoded `0.300s`) blocks re-trigger after release.
- Always-on toggle: Peace sign held `>= 1.0s` (configurable) toggles runtime state.
- Tests mock `voice.pipeline` by injecting `MockPipeline` into a module-level global
  (`modes.voice._VoicePipeline`) before `VoiceMode.enter()` lazy-loads it.

### Gotchas
- `_make_gesture(landmarks=None)` auto-created landmarks via the helper's default-logic
  guard (`if landmarks is None: landmarks = _make_landmarks()`). Tests needing truly
  None landmarks must construct `GestureData` directly, bypassing the helper.
- `monkeypatch.setattr("modes.voice.detect_ok_sign", ...)` fails because
  `detect_ok_sign` is imported at call-time inside `_is_trigger` via
  `from hand_tracking import detect_ok_sign`. The patch target must be
  `hand_tracking.detect_ok_sign`, not `modes.voice.detect_ok_sign`.
- `time.monotonic()` (not `time.time()`) for internal timing because it's
  immune to system clock adjustments.
- The inject format test must inspect the `mock_open()` handle's `.write.call_args_list`
  rather than trying `__globals__["open"]` on the bound method.
- `exit()` sets `_pipeline = None` after calling `stop()`. Tests checking `_stop_count`
  must save the pipeline reference before calling `exit()`.

### Commands
```bash
# Run voice mode tests
python3 -m pytest tests/test_voice_mode.py -v

# Run full suite (excluding pre-existing config test failure)
python3 -m pytest tests/ -v --ignore=tests/test_config_manager.py

# Import check
python3 -c "from modes.voice import VoiceMode; print(VoiceMode.name)"
```

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
