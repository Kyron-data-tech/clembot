"""
app/platform_layer

Cross-platform hardware, OS, and desktop abstraction layer for Clembot.
Supports Windows 10/11 and macOS (Apple Silicon arm64).
"""

from app.platform_layer.base import PlatformAdapter
from app.platform_layer.factory import PlatformFactory, platform_adapter
from app.platform_layer.keymap import KeyMap

__all__ = ["PlatformAdapter", "PlatformFactory", "platform_adapter", "KeyMap"]
