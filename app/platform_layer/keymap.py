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

    @classmethod
    def bookmarks_list(cls) -> List[str]:
        return ["command", "option", "b"] if IS_MACOS else ["ctrl", "shift", "o"]

    @classmethod
    def address_bar(cls) -> List[str]:
        return ["command", "l"] if IS_MACOS else ["ctrl", "l"]

    @classmethod
    def find_in_page(cls) -> List[str]:
        return ["command", "f"] if IS_MACOS else ["ctrl", "f"]

    @classmethod
    def clear_browsing_data(cls) -> List[str]:
        return ["command", "shift", "delete"] if IS_MACOS else ["ctrl", "shift", "delete"]

    @classmethod
    def browser_task_manager(cls) -> List[str]:
        return ["shift", "escape"]

    @classmethod
    def go_back(cls) -> List[str]:
        return ["command", "["] if IS_MACOS else ["alt", "left"]

    @classmethod
    def go_forward(cls) -> List[str]:
        return ["command", "]"] if IS_MACOS else ["alt", "right"]

    @classmethod
    def last_tab(cls) -> List[str]:
        return ["command", "9"] if IS_MACOS else ["ctrl", "9"]

    @classmethod
    def new_window(cls) -> List[str]:
        return ["command", "n"] if IS_MACOS else ["ctrl", "n"]

    # Window Switching & Management Shortcuts
    @classmethod
    def switch_window(cls) -> List[str]:
        return ["command", "tab"] if IS_MACOS else ["alt", "tab"]

    @classmethod
    def switch_same_app_window(cls) -> List[str]:
        return ["command", "`"] if IS_MACOS else ["alt", "tab"]

    @classmethod
    def task_view(cls) -> List[str]:
        return ["ctrl", "up"] if IS_MACOS else ["win", "tab"]

    @classmethod
    def full_screen(cls) -> List[str]:
        return ["ctrl", "command", "f"] if IS_MACOS else ["f11"]

    @classmethod
    def next_desktop(cls) -> List[str]:
        return ["ctrl", "right"] if IS_MACOS else ["win", "ctrl", "right"]

    @classmethod
    def prev_desktop(cls) -> List[str]:
        return ["ctrl", "left"] if IS_MACOS else ["win", "ctrl", "left"]

    # VS Code IDE Shortcuts
    @classmethod
    def vscode_quick_open(cls) -> List[str]:
        return ["command", "p"] if IS_MACOS else ["ctrl", "p"]

    @classmethod
    def vscode_command_palette(cls) -> List[str]:
        return ["command", "shift", "p"] if IS_MACOS else ["ctrl", "shift", "p"]

    @classmethod
    def vscode_terminal(cls) -> List[str]:
        return ["ctrl", "`"]

    @classmethod
    def vscode_toggle_sidebar(cls) -> List[str]:
        return ["command", "b"] if IS_MACOS else ["ctrl", "b"]

    @classmethod
    def vscode_settings(cls) -> List[str]:
        return ["command", ","] if IS_MACOS else ["ctrl", ","]

    @classmethod
    def vscode_goto_symbol(cls) -> List[str]:
        return ["command", "shift", "o"] if IS_MACOS else ["ctrl", "shift", "o"]

    @classmethod
    def vscode_goto_definition(cls) -> List[str]:
        return ["f12"]

    @classmethod
    def vscode_format(cls) -> List[str]:
        return ["shift", "option", "f"] if IS_MACOS else ["shift", "alt", "f"]

    @classmethod
    def vscode_search_project(cls) -> List[str]:
        return ["command", "shift", "f"] if IS_MACOS else ["ctrl", "shift", "f"]

    @classmethod
    def vscode_duplicate_line(cls) -> List[str]:
        return ["shift", "option", "down"] if IS_MACOS else ["shift", "alt", "down"]

    @classmethod
    def vscode_move_line_up(cls) -> List[str]:
        return ["option", "up"] if IS_MACOS else ["alt", "up"]

    @classmethod
    def vscode_move_line_down(cls) -> List[str]:
        return ["option", "down"] if IS_MACOS else ["alt", "down"]

    @classmethod
    def vscode_indent(cls) -> List[str]:
        return ["command", "]"] if IS_MACOS else ["ctrl", "]"]

    @classmethod
    def vscode_outdent(cls) -> List[str]:
        return ["command", "["] if IS_MACOS else ["ctrl", "["]

    @classmethod
    def vscode_select_line(cls) -> List[str]:
        return ["command", "l"] if IS_MACOS else ["ctrl", "l"]

    @classmethod
    def vscode_replace_all(cls) -> List[str]:
        return ["command", "option", "f"] if IS_MACOS else ["ctrl", "h"]
