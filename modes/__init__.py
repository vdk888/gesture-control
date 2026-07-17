from modes.base import Mode, GestureData

# -- New unified modes (v2 architecture) ----------------------------------

try:
    from modes.cursor import CursorMode  # noqa: F401
except ImportError:
    CursorMode = None  # type: ignore[assignment]

try:
    from modes.system import SystemMode  # noqa: F401
except ImportError:
    SystemMode = None  # type: ignore[assignment]

try:
    from modes.voice import VoiceMode  # noqa: F401
except ImportError:
    VoiceMode = None  # type: ignore[assignment]

# -- Backward-compat: old single-purpose modes ----------------------------
# These stay in the codebase and still work if manually enabled via config,
# but are removed from the default cycle.

try:
    from modes.mouse import MouseMode  # noqa: F401
except ImportError:
    MouseMode = None  # type: ignore[assignment]

try:
    from modes.volume import VolumeMode  # noqa: F401
except ImportError:
    VolumeMode = None  # type: ignore[assignment]

try:
    from modes.media import MediaMode  # noqa: F401
except ImportError:
    MediaMode = None  # type: ignore[assignment]

try:
    from modes.brightness import BrightnessMode  # noqa: F401
except ImportError:
    BrightnessMode = None  # type: ignore[assignment]

try:
    from modes.scroll import ScrollMode  # noqa: F401
except ImportError:
    ScrollMode = None  # type: ignore[assignment]

try:
    from modes.spaces import SpacesMode  # noqa: F401
except ImportError:
    SpacesMode = None  # type: ignore[assignment]

try:
    from modes.custom import CustomMode  # noqa: F401
except ImportError:
    CustomMode = None  # type: ignore[assignment]


MODE_REGISTRY = {
    # v2 primary modes (default cycle)
    "cursor": CursorMode,
    "system": SystemMode,
    "voice":  VoiceMode,
    # Backward-compat: old modes still usable if manually enabled in config
    "mouse":      MouseMode,
    "volume":     VolumeMode,
    "media":      MediaMode,
    "brightness": BrightnessMode,
    "scroll":     ScrollMode,
    "spaces":     SpacesMode,
    "custom":     CustomMode,
}
