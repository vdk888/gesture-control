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
