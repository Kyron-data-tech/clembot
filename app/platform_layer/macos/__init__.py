"""
app/platform_layer/macos

macOS implementation of the PlatformAdapter interface for Clembot.
Designed for macOS (Apple Silicon M-series arm64 and Intel x86_64).
"""

from app.platform_layer.macos.adapter import MacOSPlatformAdapter

__all__ = ["MacOSPlatformAdapter"]
