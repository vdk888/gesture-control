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
