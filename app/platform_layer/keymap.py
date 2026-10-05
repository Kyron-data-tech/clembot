"""
app/platform_layer/keymap.py

Cross-platform keyboard shortcut and modifier key translation table.
Translates logical actions (copy, paste, undo, redo, new tab, close tab)
and key identifiers between Windows and macOS.
"""

import sys
from typing import List, Tuple

IS_MACOS = sys.platform == "darwin"


class KeyMap:
    """Translates keyboard shortcuts between Windows and macOS."""

    @staticmethod
    def primary_modifier() -> str:
        """Returns 'command' on macOS, 'ctrl' on Windows/Linux."""
        return "command" if IS_MACOS else "ctrl"

    @staticmethod
    def map_keys(keys: List[str]) -> List[str]:
        """
        Translates a list of key names to platform-native PyAutoGUI key names.
        Example on Mac: ['ctrl', 'c'] -> ['command', 'c']
        Example on Win: ['cmd', 'c']  -> ['ctrl', 'c']
        """
        result = []
        for k in keys:
            k_lower = k.lower().strip()
            if IS_MACOS:
                if k_lower in ("ctrl", "control"):
                    result.append("command")
                elif k_lower in ("win", "windows", "super"):
                    result.append("command")
                else:
                    result.append(k_lower)
            else:
                if k_lower in ("cmd", "command"):
                    result.append("ctrl")
                elif k_lower in ("super",):
                    result.append("win")
                else:
                    result.append(k_lower)
        return result

    # Standard Application Action Shortcuts
    @classmethod
    def copy(cls) -> List[str]:
        return ["command", "c"] if IS_MACOS else ["ctrl", "c"]

    @classmethod
    def paste(cls) -> List[str]:
        return ["command", "v"] if IS_MACOS else ["ctrl", "v"]

    @classmethod
    def select_all(cls) -> List[str]:
        return ["command", "a"] if IS_MACOS else ["ctrl", "a"]

    @classmethod
    def undo(cls) -> List[str]:
        return ["command", "z"] if IS_MACOS else ["ctrl", "z"]

    @classmethod
    def redo(cls) -> List[str]:
        # On macOS, standard redo is Cmd+Shift+Z; on Windows it is Ctrl+Y (or Ctrl+Shift+Z)
        return ["command", "shift", "z"] if IS_MACOS else ["ctrl", "y"]

    @classmethod
    def save(cls) -> List[str]:
        return ["command", "s"] if IS_MACOS else ["ctrl", "s"]

    # Browser & Window Shortcuts
    @classmethod
    def new_tab(cls) -> List[str]:
        return ["command", "t"] if IS_MACOS else ["ctrl", "t"]

    @classmethod
    def close_tab(cls) -> List[str]:
        return ["command", "w"] if IS_MACOS else ["ctrl", "w"]

    @classmethod
    def next_tab(cls) -> List[str]:
        # Both platforms support Ctrl+Tab in modern browsers
        return ["ctrl", "tab"]

    @classmethod
    def prev_tab(cls) -> List[str]:
        return ["ctrl", "shift", "tab"]

    @classmethod
    def reopen_tab(cls) -> List[str]:
        return ["command", "shift", "t"] if IS_MACOS else ["ctrl", "shift", "t"]

    @classmethod
    def reload(cls) -> List[str]:
        return ["command", "r"] if IS_MACOS else ["ctrl", "r"]

    @classmethod
    def show_history(cls) -> List[str]:
        return ["command", "y"] if IS_MACOS else ["ctrl", "h"]

    @classmethod
    def show_downloads(cls) -> List[str]:
        return ["command", "option", "l"] if IS_MACOS else ["ctrl", "j"]

    @classmethod
    def bookmark(cls) -> List[str]:
        return ["command", "d"] if IS_MACOS else ["ctrl", "d"]

    @classmethod
    def zoom_in(cls) -> List[str]:
        return ["command", "="] if IS_MACOS else ["ctrl", "="]

    @classmethod
    def zoom_out(cls) -> List[str]:
        return ["command", "-"] if IS_MACOS else ["ctrl", "-"]

    @classmethod
    def zoom_reset(cls) -> List[str]:
        return ["command", "0"] if IS_MACOS else ["ctrl", "0"]

    @classmethod
    def incognito(cls) -> List[str]:
        return ["command", "shift", "n"] if IS_MACOS else ["ctrl", "shift", "n"]

    @classmethod
    def close_app(cls) -> List[str]:
        return ["command", "q"] if IS_MACOS else ["alt", "f4"]
