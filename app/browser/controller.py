import ctypes
from ctypes import wintypes
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import psutil
import pyautogui
import uiautomation as auto

try:
    import win32con
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from app.config.settings import settings
from app.logging.logger import logger
from app.windows.apps import WindowsAppCatalog


class BrowserController:
    """
    Controls web browsing on Windows across Chrome, Brave, Edge, and Firefox.
    Handles URL navigation, search engines (Google, YouTube, GitHub, Bing, DDG),
    tab switching/counting via UIAutomation, and safe browser-context shortcuts.
    """

    SEARCH_ENGINES: Dict[str, str] = {
        "google": "https://www.google.com/search?q={query}",
        "youtube": "https://www.youtube.com/results?search_query={query}",
        "github": "https://github.com/search?q={query}",
        "bing": "https://www.bing.com/search?q={query}",
        "duckduckgo": "https://duckduckgo.com/?q={query}",
    }

    WEB_DESTINATIONS: Dict[str, str] = {
        "github": "https://github.com",
        "youtube": "https://www.youtube.com",
        "gmail": "https://mail.google.com",
        "google docs": "https://docs.google.com",
        "docs": "https://docs.google.com",
        "google sheets": "https://sheets.google.com",
        "sheets": "https://sheets.google.com",
        "google drive": "https://drive.google.com",
        "drive": "https://drive.google.com",
        "google chat": "https://chat.google.com",
        "chatgpt": "https://chatgpt.com",
        "gemini": "https://gemini.google.com",
        "claude": "https://claude.ai",
        "canva": "https://www.canva.com",
        "whatsapp": "https://web.whatsapp.com",
        "whatsapp web": "https://web.whatsapp.com",
        "netflix": "https://www.netflix.com",
        "amazon": "https://www.amazon.com",
        "google": "https://www.google.com",
        "reddit": "https://www.reddit.com",
        "stackoverflow": "https://stackoverflow.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "linkedin": "https://www.linkedin.com",
    }

    def __init__(self):
        self.apps = WindowsAppCatalog()

    def _get_browser_executable(self, preferred_browser: Optional[str] = None) -> Optional[str]:
        """Finds the browser executable."""
        browser_name = preferred_browser or settings.default_browser
        browser_name = browser_name.lower().strip()

        def _resolve_target(name: str) -> Optional[str]:
            res = self.apps.find_executable(name)
            if res:
                return res[0] if isinstance(res, tuple) else res
            return None

        if browser_name in ["chrome", "google chrome"]:
            return _resolve_target("chrome")
        elif browser_name in ["brave", "brave browser"]:
            return _resolve_target("brave")
        elif browser_name in ["edge", "microsoft edge"]:
            return _resolve_target("edge")
        elif browser_name in ["firefox", "mozilla firefox"]:
            return _resolve_target("firefox")
        else:
            # Fallback to any installed browser
            for candidate in ["chrome", "brave", "edge", "firefox"]:
                exe = _resolve_target(candidate)
                if exe:
                    return exe
        return None

    def open_url(self, raw_url: str, browser: Optional[str] = None) -> str:
        """
        Navigates to the specified URL using the requested or default browser.
        """
        url = raw_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        exe = self._get_browser_executable(browser)
        if exe:
            try:
                subprocess.Popen([exe, url])
                return f"Opening {url}."
            except Exception as e:
                logger.error(f"Failed to launch browser executable {exe}: {e}")

        # Fallback to Windows default handler
        os.startfile(url)
        return f"Opening {url}."

    def search_web(self, query: str, engine: Optional[str] = None, browser: Optional[str] = None) -> str:
        """
        Executes a web search on Google, YouTube, GitHub, Bing, or DuckDuckGo.
        """
        q = query.strip()
        if not q:
            return "Please provide a search term."

        engine_key = (engine or settings.default_search_engine).lower().strip()
        url_template = self.SEARCH_ENGINES.get(engine_key, self.SEARCH_ENGINES["google"])
        
        encoded_query = urllib.parse.quote_plus(q)
        target_url = url_template.format(query=encoded_query)

        self.open_url(target_url, browser)
        engine_name = engine_key.capitalize()
        return f"Searching {engine_name} for '{q}'."

    def open_web_destination(self, name: str, browser: Optional[str] = None) -> Optional[str]:
        """Opens a well-known site like GitHub, YouTube, or Gmail."""
        norm_name = name.lower().strip()
        if norm_name in self.WEB_DESTINATIONS:
            url = self.WEB_DESTINATIONS[norm_name]
            return self.open_url(url, browser)
        return None

    # ── Browser Context, Tab Detection & UI Automation ───────────────────────

    def get_displayed_browser(self, preferred_browser: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Detects if Google Chrome or Brave Browser is currently displayed/active on screen.
        Checks foreground window first; if not foreground and preferred_browser is specified or
        foreground is an assistant window, searches visible windows on the user desktop.
        Returns a dict: {"name": "chrome"|"brave", "hwnd": hwnd, "title": title, "pid": pid, "is_foreground": bool}
        or None if neither browser is displayed.
        """
        pref = (preferred_browser or "").strip().lower()

        # 1. Check foreground window first
        if HAS_WIN32:
            try:
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    title = win32gui.GetWindowText(hwnd) or ""
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc_name = ""
                    try:
                        proc_name = psutil.Process(pid).name().lower()
                    except Exception:
                        pass

                    is_chrome = "chrome.exe" in proc_name or title.endswith("- Google Chrome") or "google chrome" in title.lower()
                    is_brave = "brave.exe" in proc_name or title.endswith("- Brave") or "brave" in title.lower()

                    if is_chrome and (not pref or "chrome" in pref):
                        return {"name": "chrome", "hwnd": hwnd, "title": title, "pid": pid, "is_foreground": True}
                    if is_brave and (not pref or "brave" in pref):
                        return {"name": "brave", "hwnd": hwnd, "title": title, "pid": pid, "is_foreground": True}
            except Exception as e:
                logger.debug(f"Error checking foreground browser window: {e}")

        # 2. Check visible windows on desktop (if preferred browser is requested or assistant has focus)
        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            found: List[Dict[str, Any]] = []

            def _enum_cb(h, lparam):
                if user32.IsWindowVisible(h):
                    length = user32.GetWindowTextLengthW(h)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(h, buff, length + 1)
                        w_title = buff.value
                        c_pid = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(h, ctypes.byref(c_pid))
                        try:
                            pname = psutil.Process(c_pid.value).name().lower()
                            if "chrome.exe" in pname or w_title.endswith("- Google Chrome"):
                                found.append({"name": "chrome", "hwnd": h, "title": w_title, "pid": c_pid.value, "is_foreground": False})
                            elif "brave.exe" in pname or w_title.endswith("- Brave"):
                                found.append({"name": "brave", "hwnd": h, "title": w_title, "pid": c_pid.value, "is_foreground": False})
                        except Exception:
                            pass
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            cb = WNDENUMPROC(_enum_cb)
            if h_desk:
                user32.EnumDesktopWindows(h_desk, cb, 0)
                user32.CloseDesktop(h_desk)
            else:
                user32.EnumWindows(cb, 0)

            # If user explicitly asked for chrome or brave, pick that one
            if pref:
                for item in found:
                    if pref in item["name"]:
                        return item

            # If assistant/terminal/clembot is in foreground, or only one browser is running, use it
            if found:
                fg_is_other_user_app = False
                if HAS_WIN32:
                    try:
                        fg_hwnd = win32gui.GetForegroundWindow()
                        if fg_hwnd:
                            _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
                            fg_proc = psutil.Process(fg_pid).name().lower()
                            # If user is actively inside VS Code, Notepad, Word, etc., don't hijack unless preferred was specified
                            if fg_proc in ["code.exe", "notepad.exe", "winword.exe", "excel.exe"]:
                                fg_is_other_user_app = True
                    except Exception:
                        pass
                if not fg_is_other_user_app:
                    return found[0]
        except Exception as e:
            logger.debug(f"Error enumerating desktop browser windows: {e}")

        return None

    def ensure_browser_focused(self, browser_info: Dict[str, Any]) -> bool:
        """Brings the browser window to foreground and restores it if minimized."""
        hwnd = browser_info.get("hwnd")
        if not hwnd:
            return False
        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)

            # Pulse Alt key to bypass Windows SetForegroundWindow lock
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)

            if HAS_WIN32:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                else:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.SetForegroundWindow(hwnd)
            else:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)

            time.sleep(0.08)
            return True
        except Exception as e:
            logger.debug(f"Error focusing browser window {hwnd}: {e}")
            return False

    def count_tabs(self, hwnd: Optional[int] = None) -> Tuple[int, List[str]]:
        """
        Inspects browser tabs via UIAutomation.
        Returns (count, [clean_tab_titles]).
        """
        if not hwnd:
            b_info = self.get_displayed_browser()
            if not b_info:
                return 0, []
            hwnd = b_info["hwnd"]

        try:
            user32 = ctypes.windll.user32
            h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
            if h_desk:
                user32.SetThreadDesktop(h_desk)

            ctrl = auto.ControlFromHandle(hwnd)
            tab_names: List[str] = []
            for c, _ in auto.WalkControl(ctrl, maxDepth=8):
                if c.ControlType == auto.ControlType.TabItemControl:
                    raw_name = c.Name or ""
                    # Strip Chromium memory usage annotations e.g. "- Memory usage - 80.0 MB"
                    clean_name = re.sub(r'\s*-\s*Memory usage\s*-\s*.*$', '', raw_name, flags=re.IGNORECASE).strip()
                    tab_names.append(clean_name or raw_name)
            return len(tab_names), tab_names
        except Exception as e:
            logger.debug(f"Error counting tabs for hwnd {hwnd}: {e}")
            return 0, []

    # ── Guarded Browser Operations (Chrome & Brave) ──────────────────────────

    def open_new_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens a new tab in the displayed browser (Chrome or Brave)."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "t")
        b_name = b_info["name"].capitalize()
        return True, f"Opened a new tab in {b_name}."

    def switch_to_tab_number(self, tab_number: int, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """
        Switches to tab number `tab_number` in the displayed browser (Chrome or Brave).
        Verifies that enough tabs are currently open before switching.
        """
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."

        self.ensure_browser_focused(b_info)
        b_name = b_info["name"].capitalize()

        # Check tab count
        count, tab_names = self.count_tabs(b_info["hwnd"])
        if count > 0 and tab_number > count:
            return False, f"{b_name} currently only has {count} tab{'s' if count != 1 else ''} open, so tab {tab_number} cannot be opened."

        # Switch tab using hotkey or UIAutomation
        if 1 <= tab_number <= 8:
            pyautogui.hotkey("ctrl", str(tab_number))
        elif tab_number == 9 and (count <= 9 or tab_number == count):
            pyautogui.hotkey("ctrl", "9")
        else:
            try:
                ctrl = auto.ControlFromHandle(b_info["hwnd"])
                tabs = [c for c, _ in auto.WalkControl(ctrl, maxDepth=8) if c.ControlType == auto.ControlType.TabItemControl]
                if len(tabs) >= tab_number:
                    tabs[tab_number - 1].Click()
            except Exception:
                pyautogui.hotkey("ctrl", "9")

        tab_title = tab_names[tab_number - 1] if (0 <= tab_number - 1 < len(tab_names)) else ""
        if tab_title:
            return True, f"Opened tab {tab_number}: {tab_title} in {b_name}."
        return True, f"Opened tab {tab_number} in {b_name}."

    def show_history(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens search history in the displayed browser (Chrome or Brave)."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "h")
        b_name = b_info["name"].capitalize()
        return True, f"Opened search history in {b_name}."

    def show_downloads(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens the downloads tab/folder in the displayed browser (Chrome or Brave)."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "NOT_DISPLAYED"
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "j")
        b_name = b_info["name"].capitalize()
        return True, f"Opened downloads in {b_name}."

    def close_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Closes the active tab in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "w")
        b_name = b_info["name"].capitalize()
        return True, f"Closed tab in {b_name}."

    def next_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Switches to the next tab in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "tab")
        b_name = b_info["name"].capitalize()
        return True, f"Switched to next tab in {b_name}."

    def previous_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Switches to the previous tab in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "shift", "tab")
        b_name = b_info["name"].capitalize()
        return True, f"Switched to previous tab in {b_name}."

    def reopen_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Reopens the last closed tab in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "shift", "t")
        b_name = b_info["name"].capitalize()
        return True, f"Reopened closed tab in {b_name}."

    def reload(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Reloads the current page in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "r")
        b_name = b_info["name"].capitalize()
        return True, f"Reloaded page in {b_name}."

    def bookmark_page(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Bookmarks the current tab in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "d")
        b_name = b_info["name"].capitalize()
        return True, f"Bookmarked page in {b_name}."

    def zoom_in(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Zooms in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "plus")
        return True, "Zoomed in."

    def zoom_out(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Zooms out the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "-")
        return True, "Zoomed out."

    def zoom_reset(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Resets zoom in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "0")
        return True, "Reset zoom."

    def new_incognito_window(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Opens a new incognito/private window."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "shift", "n")
        b_name = b_info["name"].capitalize()
        return True, f"Opened new incognito window in {b_name}."

    def focus_address_bar(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        """Focuses the address/search bar in the displayed browser."""
        b_info = self.get_displayed_browser(preferred_browser)
        if not b_info:
            return False, "Chrome or Brave is not currently displayed. Please open or switch to Chrome or Brave first."
        self.ensure_browser_focused(b_info)
        pyautogui.hotkey("ctrl", "l")
        return True, "Address bar focused."

    # Legacy static helpers returning plain string
    @staticmethod
    def new_tab() -> str:
        pyautogui.hotkey("ctrl", "t")
        return "Opened new tab."
