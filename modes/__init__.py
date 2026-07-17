from modes.base import Mode, GestureData

# Forward imports for mode classes created in tasks 5-8.
# Wrapped in try/except so the package is importable before all modes exist.
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

try:
    from modes.voice import VoiceMode  # noqa: F401
except ImportError:
    VoiceMode = None  # type: ignore[assignment]

MODE_REGISTRY = {
    "mouse": MouseMode,
    "volume": VolumeMode,
    "media": MediaMode,
    "brightness": BrightnessMode,
    "scroll": ScrollMode,
    "spaces": SpacesMode,
    "custom": CustomMode,
    "voice": VoiceMode,
}
