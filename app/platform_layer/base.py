"""
app/platform_layer/base.py

Abstract base class defining the PlatformAdapter interface for Clembot.
Every operating-system-touching operation (apps, filesystem, window management,
browser automation, audio/volume, hotkeys, and permissions) is encapsulated here.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from app.tts.base import BaseTTSProvider


class PlatformAdapter(ABC):
    """
    Unified abstract interface for operating system operations across Windows and macOS.
    No OS-specific imports (pywin32, winreg, AppKit, etc.) should exist in core application
    logic; everything must be routed through this adapter.
    """

    # ── 1. Application Management ──────────────────────────────────────────────

    @abstractmethod
    def open_application(self, name_or_target: str) -> Tuple[bool, str]:
        """Launches or brings to foreground the requested application."""
        ...

    @abstractmethod
    def close_application(self, name_or_target: str) -> Tuple[bool, str]:
        """Gracefully closes or terminates the requested application."""
        ...

    @abstractmethod
    def is_app_running(self, name: str) -> bool:
        """Checks if any process matching `name` is currently active."""
        ...

    @abstractmethod
    def find_application(self, name: str) -> Optional[Dict[str, Any]]:
        """Locates application metadata, executable path, or bundle identifier."""
        ...

    # ── 2. Filesystem & Path Resolution ────────────────────────────────────────

    @abstractmethod
    def open_path(self, path: Union[str, Path]) -> str:
        """Opens a file or folder using the default OS application or file manager."""
        ...

    @abstractmethod
    def open_folder(self, path: Union[str, Path]) -> str:
        """Opens a directory in the native file manager (Explorer / Finder)."""
        ...

    @abstractmethod
    def open_file(self, path: Union[str, Path]) -> str:
        """Opens a file with its default registered system application."""
        ...

    @abstractmethod
    def trash_path(self, path: Path) -> str:
        """Safely sends a file or directory to the OS Trash / Recycle Bin."""
        ...

    @abstractmethod
    def get_user_home(self) -> Path:
        """Returns the current user profile or home directory."""
        ...

    @abstractmethod
    def get_standard_folders(self) -> Dict[str, Path]:
        """Returns canonical user folders (Desktop, Documents, Downloads, Pictures, etc.)."""
        ...

    @abstractmethod
    def get_active_folder(self) -> Optional[Path]:
        """Queries the active folder in File Explorer (Windows) or Finder (macOS)."""
        ...

    @abstractmethod
    def get_config_dir(self) -> Path:
        """Returns Clembot configuration directory (%APPDATA%/Clembot or ~/Library/Application Support/Clembot)."""
        ...

    @abstractmethod
    def get_cache_dir(self) -> Path:
        """Returns Clembot cache directory (%LOCALAPPDATA%/Clembot or ~/Library/Caches/Clembot)."""
        ...

    @abstractmethod
    def resolve_spoken_path(self, spoken_text: str, context_base: Optional[Path] = None) -> Optional[Path]:
        """Resolves spoken folder, drive, or file expressions into concrete Paths."""
        ...

    @abstractmethod
    def find_files(self, query: str, scope: Optional[Path] = None, max_results: int = 5) -> List[Path]:
        """Searches user directories for files matching query."""
        ...

    @abstractmethod
    def is_protected_system_path(self, path: Path) -> bool:
        """Checks if a target path is an OS system critical directory (e.g. C:\\Windows or /System)."""
        ...

    @abstractmethod
    def get_dangerous_shell_patterns(self) -> List[Tuple[Any, str]]:
        """Returns regex patterns for dangerous shell commands blocked on this OS."""
        ...

    # ── 3. Window Management ───────────────────────────────────────────────────

    @abstractmethod
    def get_focused_window(self) -> Dict[str, Any]:
        """Returns metadata of currently focused window ({'id': ..., 'title': ..., 'pid': ..., 'app': ...})."""
        ...

    @abstractmethod
    def capture_foreground_window(self) -> None:
        """Snapshots the active window before Clembot focuses to handle close/minimize accurately."""
        ...

    @abstractmethod
    def focus_window(self, target: Any) -> bool:
        """Brings the specified window handle / window ID to foreground."""
        ...

    @abstractmethod
    def minimize_window(self) -> str:
        """Minimizes the currently active window."""
        ...

    @abstractmethod
    def maximize_window(self) -> str:
        """Maximizes / zooms the currently active window."""
        ...

    @abstractmethod
    def restore_window(self) -> str:
        """Restores the currently active window to normal dimensions."""
        ...

    @abstractmethod
    def close_window(self) -> str:
        """Closes the currently active window."""
        ...

    @abstractmethod
    def snap_window(self, side: str) -> str:
        """Snaps window left, right, or center."""
        ...

    @abstractmethod
    def show_desktop(self) -> str:
        """Hides/minimizes all windows to display the desktop."""
        ...

    # ── 4. Browser Automation ──────────────────────────────────────────────────

    @abstractmethod
    def get_displayed_browser(self, preferred_browser: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Detects if Chrome, Brave, Edge, or Firefox is currently displayed on screen."""
        ...

    @abstractmethod
    def count_and_list_browser_tabs(self, browser_info: Optional[Dict[str, Any]] = None) -> Tuple[int, List[str]]:
        """Returns tab count and clean tab titles for the frontmost browser."""
        ...

    @abstractmethod
    def switch_browser_tab(self, tab_num: int, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Switches to the requested 1-indexed tab in Chrome or Brave."""
        ...

    @abstractmethod
    def new_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens a new tab in the active browser."""
        ...

    @abstractmethod
    def close_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Closes the current tab in the active browser."""
        ...

    @abstractmethod
    def next_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Switches to the next browser tab."""
        ...

    @abstractmethod
    def prev_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Switches to the previous browser tab."""
        ...

    @abstractmethod
    def reopen_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Reopens the last closed browser tab."""
        ...

    @abstractmethod
    def reload_browser(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Reloads the active browser webpage."""
        ...

    @abstractmethod
    def show_browser_history(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens browser history."""
        ...

    @abstractmethod
    def show_browser_downloads(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens browser downloads page or downloads folder."""
        ...

    @abstractmethod
    def bookmark_browser_page(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Bookmarks the current webpage."""
        ...

    @abstractmethod
    def browser_zoom(self, action: str, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Zooms browser webpage ('in', 'out', 'reset')."""
        ...

    @abstractmethod
    def browser_incognito(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens a new private/incognito browsing window."""
        ...

    # ── 5. System Controls, Audio & Input ──────────────────────────────────────

    @abstractmethod
    def volume_up(self, steps: int = 5) -> str:
        """Increases master output volume."""
        ...

    @abstractmethod
    def volume_down(self, steps: int = 5) -> str:
        """Decreases master output volume."""
        ...

    @abstractmethod
    def volume_mute_toggle(self) -> str:
        """Toggles audio mute on master output."""
        ...

    @abstractmethod
    def capture_screenshot(self, destination_folder: Optional[Path] = None) -> Tuple[Path, str]:
        """Captures primary display and saves an optimized binary image under 100 KB."""
        ...

    @abstractmethod
    def send_hotkey(self, *keys: str) -> None:
        """Executes a key combination mapped to the platform keyboard layout."""
        ...

    @abstractmethod
    def type_text(self, text: str) -> None:
        """Types unicode text safely."""
        ...

    @abstractmethod
    def press_key(self, key: str) -> None:
        """Presses a single keyboard key."""
        ...

    @abstractmethod
    def copy_to_clipboard(self, text: str) -> str:
        """Copies text to the system clipboard."""
        ...

    @abstractmethod
    def get_clipboard_text(self) -> str:
        """Retrieves text from the system clipboard."""
        ...

    @abstractmethod
    def clear_clipboard(self) -> str:
        """Empties the system clipboard."""
        ...

    # ── 6. Text-to-Speech Engine ───────────────────────────────────────────────

    @abstractmethod
    def create_tts_engine(self) -> "BaseTTSProvider":
        """Instantiates the native TTS speech provider (SAPI for Windows, Say/NSSS for macOS)."""
        ...

    # ── 7. Developer & IDE Integration ─────────────────────────────────────────

    @abstractmethod
    def get_vscode_executable(self) -> Optional[str]:
        """Finds the path to the 'code' executable or launcher command."""
        ...

    @abstractmethod
    def run_user_code_in_terminal(self, file_path: Path) -> None:
        """Spawns an interactive OS terminal (CMD/PowerShell on Windows, Terminal/zsh on macOS) to run user script."""
        ...

    # ── 8. Permissions & Diagnostics ───────────────────────────────────────────

    @abstractmethod
    def check_permissions(self) -> List[Tuple[str, bool, str]]:
        """Checks OS permissions (Microphone, Accessibility, Automation, Screen Capture)."""
        ...

    @abstractmethod
    def get_platform_name(self) -> str:
        """Returns human-readable platform description ('Windows 10/11' or 'macOS (Apple Silicon)')."""
        ...
