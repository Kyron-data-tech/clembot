"""
app/platform_layer/macos/adapter.py

macOS implementation of the PlatformAdapter interface for Clembot.
Tailored for macOS 12+ (Monterey, Ventura, Sonoma, Sequoia) and Apple Silicon (M1/M2/M3/M4 arm64).
Encapsulates all macOS-specific operations (open, osascript, say, screencapture, mdfind,
Spotlight, TCC permissions) ensuring that core logic remains 100% platform-agnostic.
"""

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.logging.logger import logger
from app.platform_layer.base import PlatformAdapter
from app.platform_layer.macos.applescript import run_applescript
from app.platform_layer.macos.apps import MacOSAppCatalog
from app.platform_layer.macos.browser import MacOSBrowserController
from app.platform_layer.macos.permissions import MacOSPermissions
from app.platform_layer.macos.system import MacOSSystemControls
from app.platform_layer.macos.tts import MacOSTTSEngine
from app.platform_layer.macos.window_mgr import MacOSWindowManager
from app.tts.base import BaseTTSProvider


class MacOSPlatformAdapter(PlatformAdapter):
    """Concrete PlatformAdapter for macOS (Apple Silicon & Intel)."""

    PROTECTED_SYSTEM_PATHS = [
        "/system",
        "/library",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/private",
        "/dev",
        "/volumes",
        "/etc",
    ]

    DANGEROUS_SHELL_PATTERNS = [
        (re.compile(r'\brm\s+-(?:r|f|rf|fr)\s+/(?:\s|$)', re.IGNORECASE), "Destructive root filesystem deletion is prohibited."),
        (re.compile(r'\bdiskutil\s+(?:eraseDisk|partitionDisk|unmountDisk)\b', re.IGNORECASE), "Disk partitioning and erasure are prohibited."),
        (re.compile(r'\b(mkfs|newfs)\b', re.IGNORECASE), "Filesystem creation is prohibited."),
        (re.compile(r'\bdd\s+if=.*?\bof=/dev/', re.IGNORECASE), "Raw block device overwriting is prohibited."),
        (re.compile(r'\bcsrutil\s+disable\b', re.IGNORECASE), "Disabling System Integrity Protection is prohibited."),
        (re.compile(r'\bnvram\s+-c\b', re.IGNORECASE), "Clearing NVRAM firmware variables is prohibited."),
    ]

    FOLDER_ALIASES: Dict[str, str] = {
        "desktop": "Desktop",
        "my desktop": "Desktop",
        "documents": "Documents",
        "my documents": "Documents",
        "downloads": "Downloads",
        "my downloads": "Downloads",
        "pictures": "Pictures",
        "my pictures": "Pictures",
        "photos": "Pictures",
        "movies": "Movies",
        "my movies": "Movies",
        "music": "Music",
        "my music": "Music",
        "home": "Home",
        "user profile": "Home",
    }

    def __init__(self):
        self._app_catalog = MacOSAppCatalog()
        self._window_mgr = MacOSWindowManager()
        self._browser_ctrl = MacOSBrowserController()

    # ── 1. Application Management ──────────────────────────────────────────────

    def open_application(self, name_or_target: str) -> Tuple[bool, str]:
        try:
            msg = self._app_catalog.open_or_activate(name_or_target)
            return True, msg
        except Exception as e:
            logger.warning(f"macOS open_application failed for '{name_or_target}': {e}")
            return False, str(e)

    def close_application(self, name_or_target: str) -> Tuple[bool, str]:
        try:
            msg = self._app_catalog.close_app(name_or_target)
            return True, msg
        except Exception as e:
            logger.warning(f"macOS close_application failed for '{name_or_target}': {e}")
            return False, str(e)

    def is_app_running(self, name: str) -> bool:
        return self._app_catalog.is_app_running(name)

    def find_application(self, name: str) -> Optional[Dict[str, Any]]:
        res = self._app_catalog.find_app_bundle(name)
        if res:
            canonical, path = res
            return {"target": str(path), "type": "app_bundle", "name": canonical}
        return None

    # ── 2. Filesystem & Path Resolution ────────────────────────────────────────

    def open_path(self, path: Union[str, Path]) -> str:
        target = Path(path) if not isinstance(path, Path) else path
        if target.is_dir():
            return self.open_folder(target)
        return self.open_file(target)

    def open_folder(self, path: Union[str, Path]) -> str:
        target = Path(path) if not isinstance(path, Path) else path
        if not target.exists():
            raise FileNotFoundError(f"Folder not found: {target}")
        if not target.is_dir():
            target = target.parent

        subprocess.Popen(["/usr/bin/open", str(target)])
        return f"Opening {target.name or str(target)}."

    def open_file(self, path: Union[str, Path]) -> str:
        target = Path(path) if not isinstance(path, Path) else path
        if not target.exists():
            raise FileNotFoundError(f"File not found: {target}")

        subprocess.Popen(["/usr/bin/open", str(target)])
        return f"Opening {target.name}."

    def trash_path(self, path: Path) -> str:
        import send2trash
        send2trash.send2trash(str(path))
        return f"Moved '{path.name}' to the macOS Trash."

    def get_user_home(self) -> Path:
        return Path.home()

    def get_standard_folders(self) -> Dict[str, Path]:
        home = Path.home()
        return {
            "Home": home,
            "Desktop": home / "Desktop",
            "Documents": home / "Documents",
            "Downloads": home / "Downloads",
            "Pictures": home / "Pictures",
            "Music": home / "Music",
            "Movies": home / "Movies",
        }

    def get_active_folder(self) -> Optional[Path]:
        """Queries the active folder open in the frontmost Finder window."""
        script = '''
        tell application "Finder"
            try
                if (exists front window) then
                    return POSIX path of (target of front window as alias)
                end if
                return ""
            on error
                return ""
            end try
        end tell
        '''
        success, out = run_applescript(script)
        if success and out.strip():
            p = Path(out.strip())
            if p.is_dir():
                return p
        return None

    def get_config_dir(self) -> Path:
        p = Path.home() / "Library" / "Application Support" / "Clembot"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_cache_dir(self) -> Path:
        p = Path.home() / "Library" / "Caches" / "Clembot"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve_spoken_path(self, spoken_text: str, context_base: Optional[Path] = None) -> Optional[Path]:
        clean = spoken_text.strip()
        lower = clean.lower()
        std = self.get_standard_folders()

        if lower in self.FOLDER_ALIASES:
            canonical = self.FOLDER_ALIASES[lower]
            return std.get(canonical, std["Desktop"])

        # Check location matches: "projects on desktop"
        m = re.search(r'^(.*?)\s+(?:on|in|under|inside)\s+(desktop|downloads|documents|pictures|music|movies)$', lower)
        if m:
            sub = m.group(1).strip()
            loc = self.FOLDER_ALIASES.get(m.group(2).strip(), "Desktop")
            parent = std.get(loc, std["Desktop"])
            return parent / sub

        # Direct path check
        p = Path(clean)
        if p.is_absolute() and p.exists():
            return p

        # Check in context_base
        if context_base and (context_base / clean).exists():
            return context_base / clean

        # Check in Desktop or Downloads
        for key in ["Desktop", "Downloads", "Documents"]:
            cand = std[key] / clean
            if cand.exists():
                return cand

        return None

    def find_files(self, query: str, scope: Optional[Path] = None, max_results: int = 5) -> List[Path]:
        q = query.strip()
        if not q:
            return []

        # 1. Fast Spotlight search via /usr/bin/mdfind
        try:
            cmd = ["/usr/bin/mdfind"]
            if scope and scope.is_dir():
                cmd.extend(["-onlyin", str(scope)])
            cmd.append(f"kMDItemFSName == '*{q}*'c")

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5)
            if proc.returncode == 0 and proc.stdout.strip():
                lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
                results: List[Path] = []
                for line in lines:
                    p = Path(line)
                    # Filter out hidden or noise files
                    if not p.name.startswith(".") and p.exists():
                        results.append(p)
                        if len(results) >= max_results:
                            break
                if results:
                    return results
        except Exception as e:
            logger.debug(f"macOS mdfind search failed: {e}")

        # 2. Bounded directory walk fallback
        roots = [scope] if scope and scope.is_dir() else [
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path.home() / "Documents",
        ]
        results = []
        for root in roots:
            if not root.is_dir():
                continue
            for r, dirs, files in os.walk(str(root)):
                # prune hidden folders
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    if q.lower() in f.lower() and not f.startswith("."):
                        results.append(Path(r) / f)
                        if len(results) >= max_results:
                            return results
        return results

    def is_protected_system_path(self, path: Path) -> bool:
        try:
            resolved = str(path.resolve()).lower()
            if resolved in ["/", "/system", "/library", "/bin", "/sbin", "/usr"]:
                return True
            for p in self.PROTECTED_SYSTEM_PATHS:
                if resolved == p or resolved.startswith(f"{p}/"):
                    return True
        except Exception:
            pass
        return False

    def get_dangerous_shell_patterns(self) -> List[Tuple[Any, str]]:
        return self.DANGEROUS_SHELL_PATTERNS

    # ── 3. Window Management ───────────────────────────────────────────────────

    def get_focused_window(self) -> Dict[str, Any]:
        return self._window_mgr.get_focused_window()

    def capture_foreground_window(self) -> None:
        self._window_mgr.capture_foreground_window()

    def focus_window(self, target: Any) -> bool:
        return self._window_mgr.focus_window(target)

    def minimize_window(self) -> str:
        return self._window_mgr.minimize_current()

    def maximize_window(self) -> str:
        return self._window_mgr.maximize_current()

    def restore_window(self) -> str:
        return self._window_mgr.restore_current()

    def close_window(self) -> str:
        return self._window_mgr.close_current()

    def snap_window(self, side: str) -> str:
        side_lower = side.lower().strip()
        if side_lower == "left":
            return self._window_mgr.snap_left()
        elif side_lower == "right":
            return self._window_mgr.snap_right()
        elif side_lower in ("center", "middle"):
            return self._window_mgr.center_window()
        return f"Unsupported snap side: '{side}'."

    def show_desktop(self) -> str:
        return self._window_mgr.show_desktop()

    # ── 4. Browser Automation ──────────────────────────────────────────────────

    def get_displayed_browser(self, preferred_browser: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._browser_ctrl.get_displayed_browser(preferred_browser)

    def count_and_list_browser_tabs(self, browser_info: Optional[Dict[str, Any]] = None) -> Tuple[int, List[str]]:
        return self._browser_ctrl.count_and_list_browser_tabs(browser_info)

    def switch_browser_tab(self, tab_num: int, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.switch_browser_tab(tab_num, preferred_browser)

    def new_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.new_browser_tab(preferred_browser)

    def close_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.close_browser_tab(preferred_browser)

    def next_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.next_browser_tab(preferred_browser)

    def prev_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.prev_browser_tab(preferred_browser)

    def reopen_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.reopen_browser_tab(preferred_browser)

    def reload_browser(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.reload_browser(preferred_browser)

    def show_browser_history(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.show_browser_history(preferred_browser)

    def show_browser_downloads(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.show_browser_downloads(preferred_browser)

    def bookmark_browser_page(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.bookmark_browser_page(preferred_browser)

    def browser_zoom(self, action: str, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.browser_zoom(action, preferred_browser)

    def browser_incognito(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.browser_incognito(preferred_browser)

    # ── 5. System Controls, Audio & Input ──────────────────────────────────────

    def volume_up(self, steps: int = 5) -> str:
        return MacOSSystemControls.volume_up(steps)

    def volume_down(self, steps: int = 5) -> str:
        return MacOSSystemControls.volume_down(steps)

    def volume_mute_toggle(self) -> str:
        return MacOSSystemControls.volume_mute_toggle()

    def capture_screenshot(self, destination_folder: Optional[Path] = None) -> Tuple[Path, str]:
        return MacOSSystemControls.capture_screenshot(destination_folder)

    def send_hotkey(self, *keys: str) -> None:
        MacOSSystemControls.send_hotkey(*keys)

    def type_text(self, text: str) -> None:
        MacOSSystemControls.type_text(text)

    def press_key(self, key: str) -> None:
        MacOSSystemControls.press_key(key)

    def copy_to_clipboard(self, text: str) -> str:
        return MacOSSystemControls.copy_text(text)

    def get_clipboard_text(self) -> str:
        return MacOSSystemControls.get_text()

    def clear_clipboard(self) -> str:
        return MacOSSystemControls.clear()

    # ── 6. Text-to-Speech Engine ───────────────────────────────────────────────

    def create_tts_engine(self) -> BaseTTSProvider:
        return MacOSTTSEngine()

    # ── 7. Developer & IDE Integration ─────────────────────────────────────────

    def get_vscode_executable(self) -> Optional[str]:
        # 1. System PATH
        which_code = shutil.which("code")
        if which_code:
            return which_code

        # 2. Standard macOS VS Code bundle binary
        app_code = Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code")
        if app_code.exists():
            return str(app_code)

        user_app_code = Path.home() / "Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
        if user_app_code.exists():
            return str(user_app_code)

        return None

    def run_user_code_in_terminal(self, file_path: Path) -> None:
        """Spawns macOS Terminal to run user script with python3."""
        script = f'''
        tell application "Terminal"
            do script "python3 '{file_path}'"
            activate
        end tell
        '''
        run_applescript(script)

    # ── 8. Permissions & Diagnostics ───────────────────────────────────────────

    def check_permissions(self) -> List[Tuple[str, bool, str]]:
        return MacOSPermissions.check_all()

    def get_platform_name(self) -> str:
        arch = platform.machine()
        is_silicon = "arm" in arch.lower() or "aarch64" in arch.lower()
        suffix = "Apple Silicon arm64" if is_silicon else arch
        return f"macOS ({suffix})"
