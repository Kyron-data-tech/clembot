"""
app/platform_layer/macos/browser.py

Native macOS browser controller for Google Chrome and Brave Browser via AppleScript.
Communicates directly with Chromium's AppleScript suite for ultra-fast, zero-dependency
tab listing, counting, and switching.
"""

import subprocess
import urllib.parse
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from app.logging.logger import logger
from app.platform_layer.macos.applescript import run_applescript, run_multiline_applescript


class MacOSBrowserController:
    """Controls Google Chrome and Brave Browser on macOS via AppleScript."""

    SUPPORTED_BROWSERS = {
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "brave": "Brave Browser",
        "brave browser": "Brave Browser",
    }

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

    def open_url(self, raw_url: str, browser: Optional[str] = None) -> str:
        url = raw_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        app_name = self._resolve_app_name(browser)
        if app_name:
            subprocess.Popen(["/usr/bin/open", "-a", app_name, url])
        else:
            webbrowser.open(url)
        return f"Opening {url}."

    def search_web(self, query: str, engine: Optional[str] = None, browser: Optional[str] = None) -> str:
        q = query.strip()
        if not q:
            return "Please provide a search term."
        engine_key = (engine or "google").lower().strip()
        template = self.SEARCH_ENGINES.get(engine_key, self.SEARCH_ENGINES["google"])
        target_url = template.format(query=urllib.parse.quote_plus(q))
        self.open_url(target_url, browser)
        return f"Searching {engine_key.capitalize()} for '{q}'."

    def open_web_destination(self, name: str, browser: Optional[str] = None) -> Optional[str]:
        norm = name.lower().strip()
        if norm in self.WEB_DESTINATIONS:
            url = self.WEB_DESTINATIONS[norm]
            self.open_url(url, browser)
            return f"Opening {name}."
        return None

    def _resolve_app_name(self, preferred_browser: Optional[str] = None) -> Optional[str]:
        """Resolves the active or preferred browser app name."""
        if preferred_browser:
            clean = preferred_browser.strip().lower()
            if clean in self.SUPPORTED_BROWSERS:
                return self.SUPPORTED_BROWSERS[clean]

        # Check if Chrome or Brave is running
        for key in ["Google Chrome", "Brave Browser"]:
            res, out = run_applescript(f'application "{key}" is running')
            if res and out.strip() == "true":
                # Check if it has a front window
                w_res, w_out = run_applescript(f'tell application "{key}" to return (count of windows) > 0')
                if w_res and w_out.strip() == "true":
                    return key

        return None

    def get_displayed_browser(self, preferred_browser: Optional[str] = None) -> Optional[Dict[str, Any]]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return None
        return {"name": "chrome" if "Chrome" in app_name else "brave", "app_name": app_name}

    def count_and_list_browser_tabs(self, browser_info: Optional[Dict[str, Any]] = None) -> Tuple[int, List[str]]:
        """Returns tab count and titles using AppleScript."""
        app_name = browser_info.get("app_name") if browser_info else self._resolve_app_name()
        if not app_name:
            return 0, []

        script = f'''
        tell application "{app_name}"
            if not (exists front window) then return ""
            set out to ""
            repeat with t in tabs of front window
                set out to out & (title of t) & "|||"
            end repeat
            return out
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if not success or not out:
            return 0, []

        titles = [t.strip() for t in out.split("|||") if t.strip()]
        return len(titles), titles

    def switch_browser_tab(self, tab_num: int, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running. Please open Chrome or Brave first."

        count, titles = self.count_and_list_browser_tabs({"app_name": app_name})
        if count > 0 and tab_num > count:
            return False, f"{app_name} currently only has {count} tab{'s' if count != 1 else ''} open, so tab {tab_num} cannot be opened."

        script = f'''
        tell application "{app_name}"
            activate
            if (exists front window) then
                set active tab index of front window to {tab_num}
            end if
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not switch to tab {tab_num}: {err}"

        tab_title = titles[tab_num - 1] if (0 <= tab_num - 1 < len(titles)) else ""
        if tab_title:
            return True, f"Opened tab {tab_num}: {tab_title} in {app_name}."
        return True, f"Opened tab {tab_num} in {app_name}."

    def new_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running. Please open Chrome or Brave first."

        script = f'''
        tell application "{app_name}"
            activate
            if (exists front window) then
                tell front window to make new tab
            else
                make new window
            end if
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not open new tab: {err}"
        return True, f"Opened a new tab in {app_name}."

    def close_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        script = f'''
        tell application "{app_name}"
            activate
            if (exists front window) then
                tell active tab of front window to close
            end if
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not close tab: {err}"
        return True, f"Closed tab in {app_name}."

    def next_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        script = f'''
        tell application "{app_name}"
            activate
            if (exists front window) then
                set idx to active tab index of front window
                set cnt to count of tabs of front window
                if idx < cnt then
                    set active tab index of front window to (idx + 1)
                else
                    set active tab index of front window to 1
                end if
            end if
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not switch to next tab: {err}"
        return True, f"Switched to next tab in {app_name}."

    def prev_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        script = f'''
        tell application "{app_name}"
            activate
            if (exists front window) then
                set idx to active tab index of front window
                set cnt to count of tabs of front window
                if idx > 1 then
                    set active tab index of front window to (idx - 1)
                else
                    set active tab index of front window to cnt
                end if
            end if
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not switch to previous tab: {err}"
        return True, f"Switched to previous tab in {app_name}."

    def reopen_browser_tab(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        # Reopen last closed tab via shortcut Cmd+Shift+T
        script = f'''
        tell application "{app_name}" to activate
        tell application "System Events"
            keystroke "t" using {{command down, shift down}}
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not reopen closed tab: {err}"
        return True, f"Reopened closed tab in {app_name}."

    def reload_browser(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        script = f'''
        tell application "{app_name}"
            activate
            if (exists front window) then
                tell active tab of front window to reload
            end if
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not reload tab: {err}"
        return True, f"Reloaded page in {app_name}."

    def show_browser_history(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        # Chromium on macOS: Cmd+Y opens History
        script = f'''
        tell application "{app_name}" to activate
        tell application "System Events"
            keystroke "y" using command down
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not open history: {err}"
        return True, f"Opened search history in {app_name}."

    def show_browser_downloads(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "NOT_DISPLAYED"

        # Chromium on macOS: Cmd+Shift+J opens Downloads
        script = f'''
        tell application "{app_name}" to activate
        tell application "System Events"
            keystroke "j" using {{command down, shift down}}
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not open downloads: {err}"
        return True, f"Opened downloads in {app_name}."

    def bookmark_browser_page(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        script = f'''
        tell application "{app_name}" to activate
        tell application "System Events"
            keystroke "d" using command down
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not bookmark page: {err}"
        return True, f"Bookmarked page in {app_name}."

    def browser_zoom(self, action: str, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        act = action.lower().strip()
        key = "=" if act == "in" else ("-" if act == "out" else "0")

        script = f'''
        tell application "{app_name}" to activate
        tell application "System Events"
            keystroke "{key}" using command down
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            return False, f"Could not zoom: {err}"
        return True, f"Zoom {act} applied."

    def browser_incognito(self, preferred_browser: Optional[str] = None) -> Tuple[bool, str]:
        app_name = self._resolve_app_name(preferred_browser)
        if not app_name:
            return False, "Chrome or Brave is not currently running."

        # Chromium AppleScript supports make new window with properties {mode:"incognito"}
        script = f'''
        tell application "{app_name}"
            activate
            make new window with properties {{mode:"incognito"}}
        end tell
        '''
        success, err = run_multiline_applescript(script)
        if not success:
            # Fallback to keyboard shortcut Cmd+Shift+N
            kb_script = f'''
            tell application "{app_name}" to activate
            tell application "System Events"
                keystroke "n" using {{command down, shift down}}
            end tell
            '''
            success, err = run_multiline_applescript(kb_script)

        if not success:
            return False, f"Could not open incognito window: {err}"
        return True, f"Opened new incognito window in {app_name}."
