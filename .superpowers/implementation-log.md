# Gesture Control v2 -- Implementation Log

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
