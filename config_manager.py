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
    try:
        if config.get("pinch_on", 0) >= config.get("pinch_off", 1):
            errors.append("pinch_on must be less than pinch_off")
    except TypeError:
        errors.append("pinch_on and pinch_off must be numbers for comparison")
    return errors
