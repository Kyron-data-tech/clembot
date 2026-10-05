"""
app/platform_layer/windows/adapter.py

Windows implementation of the PlatformAdapter interface.
Encapsulates all Windows-specific APIs (pywin32, winreg, ctypes.windll, SAPI,
PowerShell/cmd, Explorer, and UIAutomation) to guarantee that core logic never
calls OS APIs directly.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from app.automation.input_adapter import WindowsInputAdapter
from app.browser.controller import BrowserController
from app.clipboard.manager import WindowsClipboardManager
from app.filesystem.paths import WindowsPathResolver
from app.filesystem.search import FileSearchService
from app.filesystem.service import FileSystemService
from app.logging.logger import logger
from app.platform_layer.base import PlatformAdapter
from app.security.guard import SecurityGuard
from app.tts.base import BaseTTSProvider
from app.tts.sapi_engine import SAPIEngine
from app.windows.apps import WindowsAppCatalog
from app.windows.system import WindowsSystemControls
from app.windows.window_manager import WindowsWindowManager

try:
    import win32con
    import win32gui
    import win32process
    import psutil
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class WindowsPlatformAdapter(PlatformAdapter):
    """Concrete PlatformAdapter for Windows 10/11."""

    def __init__(self):
        self._app_catalog = WindowsAppCatalog()
        self._window_mgr = WindowsWindowManager()
        self._fs_service = FileSystemService()
        self._search_service = FileSearchService()
        self._browser_ctrl = BrowserController()
        self._security_guard = SecurityGuard()

    # ── 1. Application Management ──────────────────────────────────────────────

    def open_application(self, name_or_target: str) -> Tuple[bool, str]:
        try:
            msg = self._app_catalog.open_or_activate(name_or_target)
            return True, msg
        except Exception as e:
            logger.warning(f"Windows open_application failed for '{name_or_target}': {e}")
            return False, str(e)

    def close_application(self, name_or_target: str) -> Tuple[bool, str]:
        try:
            msg = self._app_catalog.close_app(name_or_target)
            return True, msg
        except Exception as e:
            logger.warning(f"Windows close_application failed for '{name_or_target}': {e}")
            return False, str(e)

    def is_app_running(self, name: str) -> bool:
        if not HAS_WIN32:
            return False
        clean = name.strip().lower()
        try:
            for proc in psutil.process_iter(["name"]):
                pname = (proc.info.get("name") or "").lower()
                if clean in pname:
                    return True
        except Exception:
            pass
        return False

    def find_application(self, name: str) -> Optional[Dict[str, Any]]:
        res = self._app_catalog.find_executable(name)
        if res:
            target, app_type = res
            return {"target": target, "type": app_type, "name": name}
        return None

    # ── 2. Filesystem & Path Resolution ────────────────────────────────────────

    def open_path(self, path: Union[str, Path]) -> str:
        target = Path(path) if not isinstance(path, Path) else path
        if target.is_dir():
            return self.open_folder(target)
        return self.open_file(target)

    def open_folder(self, path: Union[str, Path]) -> str:
        return self._fs_service.open_folder(path)

    def open_file(self, path: Union[str, Path]) -> str:
        return self._fs_service.open_file(path)

    def trash_path(self, path: Path) -> str:
        import send2trash
        send2trash.send2trash(str(path))
        return f"Moved '{path.name}' to the Windows Recycle Bin."

    def get_user_home(self) -> Path:
        return WindowsPathResolver.get_user_home()

    def get_standard_folders(self) -> Dict[str, Path]:
        return WindowsPathResolver.get_standard_folders()

    def get_active_folder(self) -> Optional[Path]:
        return WindowsPathResolver.get_active_explorer_path()

    def get_config_dir(self) -> Path:
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        p = base / "Clembot"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_cache_dir(self) -> Path:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        p = base / "Clembot"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve_spoken_path(self, spoken_text: str, context_base: Optional[Path] = None) -> Optional[Path]:
        return WindowsPathResolver.resolve_spoken_path(spoken_text, base_context=context_base)

    def find_files(self, query: str, scope: Optional[Path] = None, max_results: int = 5) -> List[Path]:
        scope_str = str(scope) if scope else None
        return self._search_service.find_files(query, scope=scope_str, max_results=max_results)

    def is_protected_system_path(self, path: Path) -> bool:
        return self._security_guard.is_protected_path(path)

    def get_dangerous_shell_patterns(self) -> List[Tuple[Any, str]]:
        return SecurityGuard.DANGEROUS_SHELL_PATTERNS

    # ── 3. Window Management ───────────────────────────────────────────────────

    def get_focused_window(self) -> Dict[str, Any]:
        if not HAS_WIN32:
            return {"id": 0, "title": "", "pid": 0, "app": ""}
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd) or ""
            _, pid = win32process.GetWindowThreadProcessId(hwnd) if hwnd else (0, 0)
            app_name = ""
            if pid:
                try:
                    app_name = psutil.Process(pid).name()
                except Exception:
                    pass
            return {"id": hwnd, "title": title, "pid": pid, "app": app_name}
        except Exception as e:
            logger.debug(f"get_focused_window error: {e}")
            return {"id": 0, "title": "", "pid": 0, "app": ""}

    def capture_foreground_window(self) -> None:
        if not HAS_WIN32:
            return
        try:
            hwnd = win32gui.GetForegroundWindow()
            self._window_mgr.last_user_hwnd = hwnd
            self._window_mgr.last_user_title = win32gui.GetWindowText(hwnd) or ""
        except Exception as e:
            logger.debug(f"capture_foreground_window error: {e}")

    def focus_window(self, target: Any) -> bool:
        if isinstance(target, int):
            if not HAS_WIN32:
                return False
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 2, 0)
                if win32gui.IsIconic(target):
                    win32gui.ShowWindow(target, win32con.SW_RESTORE)
                else:
                    win32gui.ShowWindow(target, win32con.SW_SHOW)
                win32gui.SetForegroundWindow(target)
                return True
            except Exception as e:
                logger.debug(f"focus_window hwnd {target} failed: {e}")
                return False
        elif isinstance(target, str):
            return self._app_catalog.activate_running_window(target)
        return False

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
        hwnd = browser_info.get("hwnd") if browser_info else None
        return self._browser_ctrl.count_tabs(hwnd)

    def switch_browser_tab(self, tab_num: int, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.switch_to_tab_number(tab_num, preferred_browser)

    def new_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.open_new_tab(preferred_browser)

    def close_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.close_tab(preferred_browser)

    def next_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.next_tab(preferred_browser)

    def prev_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.previous_tab(preferred_browser)

    def reopen_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.reopen_tab(preferred_browser)

    def reload_browser(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.reload(preferred_browser)

    def show_browser_history(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.show_history(preferred_browser)

    def show_browser_downloads(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.show_downloads(preferred_browser)

    def bookmark_browser_page(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.bookmark_page(preferred_browser)

    def browser_zoom(self, action: str, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        act = action.lower().strip()
        if act == "in":
            return self._browser_ctrl.zoom_in(preferred_browser)
        elif act == "out":
            return self._browser_ctrl.zoom_out(preferred_browser)
        elif act == "reset":
            return self._browser_ctrl.zoom_reset(preferred_browser)
        return False, f"Unknown zoom action: '{action}'."

    def browser_incognito(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        return self._browser_ctrl.new_incognito_window(preferred_browser)

    # ── 5. System Controls, Audio & Input ──────────────────────────────────────

    def volume_up(self, steps: int = 5) -> str:
        return WindowsSystemControls.volume_up(steps)

    def volume_down(self, steps: int = 5) -> str:
        return WindowsSystemControls.volume_down(steps)

    def volume_mute_toggle(self) -> str:
        return WindowsSystemControls.volume_mute_toggle()

    def capture_screenshot(self, destination_folder: Optional[Path] = None) -> Tuple[Path, str]:
        return WindowsSystemControls.capture_screenshot(destination_folder)

    def send_hotkey(self, *keys: str) -> None:
        WindowsInputAdapter.hotkey(list(keys))

    def type_text(self, text: str) -> None:
        WindowsInputAdapter.type_text(text)

    def press_key(self, key: str) -> None:
        WindowsInputAdapter.press_key(key)

    def copy_to_clipboard(self, text: str) -> str:
        return WindowsClipboardManager.copy_text(text)

    def get_clipboard_text(self) -> str:
        return WindowsClipboardManager.get_text()

    def clear_clipboard(self) -> str:
        return WindowsClipboardManager.clear()

    # ── 6. Text-to-Speech Engine ───────────────────────────────────────────────

    def create_tts_engine(self) -> BaseTTSProvider:
        return SAPIEngine()

    # ── 7. Developer & IDE Integration ─────────────────────────────────────────

    def get_vscode_executable(self) -> Optional[str]:
        res = self._app_catalog.find_executable("vscode")
        if res:
            return res[0]
        return shutil.which("code.cmd") or shutil.which("code")

    def run_user_code_in_terminal(self, file_path: Path) -> None:
        subprocess.Popen(
            ["cmd.exe", "/k", "python", str(file_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0
        )

    # ── 8. Permissions & Diagnostics ───────────────────────────────────────────

    def check_permissions(self) -> List[Tuple[str, bool, str]]:
        checks = []
        # 1. Microphone check via PyAudio
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            dev_count = p.get_device_count()
            p.terminate()
            checks.append(("Microphone Access", dev_count > 0, "Audio recording hardware detected" if dev_count > 0 else "No audio input devices found"))
        except Exception as e:
            checks.append(("Microphone Access", False, f"PyAudio error: {e}"))

        # 2. Windows GUI Automation / pywin32
        checks.append(("Windows Automation (pywin32)", HAS_WIN32, "pywin32 installed and active" if HAS_WIN32 else "pywin32 missing"))

        # 3. Speech API (SAPI)
        try:
            import pyttsx3
            eng = pyttsx3.init("sapi5")
            voices = eng.getProperty("voices")
            checks.append(("Windows SAPI TTS", len(voices) > 0, f"{len(voices)} SAPI voice(s) available"))
        except Exception as e:
            checks.append(("Windows SAPI TTS", False, f"SAPI initialization error: {e}"))

        return checks

    def get_platform_name(self) -> str:
        return "Windows 10/11"
