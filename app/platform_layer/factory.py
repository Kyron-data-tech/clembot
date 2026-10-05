"""
app/platform_layer/factory.py

Platform factory that detects operating system via sys.platform and lazily imports
ONLY the platform-specific adapter for the current runtime.
Guarantees that macOS users never import Windows-only modules (pywin32, winreg, etc.)
and Windows users never import macOS-only modules (pyobjc, AppKit, etc.).
"""

import sys
from typing import Optional

from app.platform_layer.base import PlatformAdapter

_CURRENT_ADAPTER: Optional[PlatformAdapter] = None


class PlatformFactory:
    """Factory creating and caching the singleton PlatformAdapter for the active OS."""

    @classmethod
    def get_adapter(cls) -> PlatformAdapter:
        global _CURRENT_ADAPTER
        if _CURRENT_ADAPTER is not None:
            return _CURRENT_ADAPTER

        platform = sys.platform.lower()

        if platform == "win32":
            from app.platform_layer.windows.adapter import WindowsPlatformAdapter
            _CURRENT_ADAPTER = WindowsPlatformAdapter()
            return _CURRENT_ADAPTER

        elif platform == "darwin":
            from app.platform_layer.macos.adapter import MacOSPlatformAdapter
            _CURRENT_ADAPTER = MacOSPlatformAdapter()
            return _CURRENT_ADAPTER

        else:
            raise NotImplementedError(
                f"Unsupported operating system: '{sys.platform}'. "
                "Clembot currently supports Windows 10/11 (win32) and macOS (darwin, Apple Silicon arm64)."
            )

    @classmethod
    def reset_adapter_for_testing(cls, custom_adapter: Optional[PlatformAdapter] = None) -> None:
        """Allows test suites to inject mock adapters."""
        global _CURRENT_ADAPTER
        _CURRENT_ADAPTER = custom_adapter


class _LazyPlatformAdapterProxy:
    """
    Convenience proxy delegating all attribute lookups to PlatformFactory.get_adapter().
    Allows `from app.platform_layer.factory import platform_adapter` without triggering
    immediate imports at module import time.
    """

    def __getattr__(self, name: str):
        adapter = PlatformFactory.get_adapter()
        return getattr(adapter, name)


platform_adapter: PlatformAdapter = _LazyPlatformAdapterProxy()  # type: ignore
