"""
app/platform_layer/macos/window_mgr.py

Window management and tiling for macOS using System Events and AppleScript.
Handles focus, minimize, maximize (AXZoom), close, and half-screen snapping.
"""

from typing import Any, Dict, Optional

from app.logging.logger import logger
from app.platform_layer.macos.applescript import run_applescript, run_multiline_applescript


class MacOSWindowManager:
    """Controls window positioning, state, and focus on macOS."""

    def __init__(self):
        self.last_user_app: str = ""
        self.last_user_title: str = ""

    def get_focused_window(self) -> Dict[str, Any]:
        """Queries the frontmost application and window title."""
        script = '''
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
                set winTitle to ""
                try
                    set winTitle to name of front window of frontApp
                end try
                return appName & "|||" & winTitle
            on error
                return ""
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and "|||" in out:
            app_name, title = out.split("|||", 1)
            return {"id": app_name.strip(), "title": title.strip(), "pid": 0, "app": app_name.strip()}
        return {"id": "", "title": "", "pid": 0, "app": ""}

    def capture_foreground_window(self) -> None:
        """Captures the active application and title before Clembot processes speech."""
        info = self.get_focused_window()
        self.last_user_app = info["app"]
        self.last_user_title = info["title"]

    APP_NAME_MAP = {
        "code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "brave": "Brave Browser",
        "brave browser": "Brave Browser",
        "terminal": "Terminal",
        "iterm": "iTerm",
        "iterm2": "iTerm2",
        "finder": "Finder",
        "calculator": "Calculator",
        "safari": "Safari",
    }

    def focus_window(self, target: Any) -> bool:
        """Activates an application by name."""
        app_name = str(target).strip()
        if not app_name:
            return False
        resolved = self.APP_NAME_MAP.get(app_name.lower(), app_name)
        success, _ = run_applescript(f'tell application "{resolved}" to activate')
        return success


    def minimize_current(self) -> str:
        """Minimizes the frontmost application window."""
        script = '''
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                set miniaturized of front window of frontApp to true
                return name of frontApp
            on error err
                return "ERROR:" & err
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and not out.startswith("ERROR:"):
            return f"Minimized {out.strip()}."
        return "No active window to minimize."

    def maximize_current(self) -> str:
        """Zooms / maximizes the frontmost window."""
        script = '''
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                tell front window of frontApp to perform action "AXZoom"
                return name of frontApp
            on error err
                return "ERROR:" & err
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and not out.startswith("ERROR:"):
            return f"Maximized {out.strip()}."
        return "No active window to maximize."

    def restore_current(self) -> str:
        """Restores the frontmost window (toggles AXZoom)."""
        return self.maximize_current()

    def close_current(self) -> str:
        """Closes the frontmost window gracefully."""
        script = '''
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
                try
                    tell front window of frontApp to perform action "AXClose"
                on error
                    keystroke "w" using command down
                end try
                return appName
            on error err
                return "ERROR:" & err
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and not out.startswith("ERROR:"):
            return f"Closed {out.strip()}."
        return "No active window to close."

    def snap_left(self) -> str:
        """Snaps the active window to the left half of the display."""
        script = '''
        set screenW to 1440
        set screenH to 900
        try
            tell application "Finder"
                set screenBounds to bounds of window of desktop
                set screenW to item 3 of screenBounds
                set screenH to item 4 of screenBounds
            end tell
        on error
            try
                tell application "Finder"
                    set screenBounds to bounds of desktop
                    set screenW to item 3 of screenBounds
                    set screenH to item 4 of screenBounds
                end tell
            end try
        end try
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                if (count of windows of frontApp) > 0 then
                    set frontWin to front window of frontApp
                    set position of frontWin to {0, 25}
                    set size of frontWin to {screenW / 2, screenH - 25}
                    return "OK"
                end if
            on error err
                return "ERROR:" & err
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and "OK" in out:
            return "Snapped window to left half."
        return "Could not snap window to left half."

    def snap_right(self) -> str:
        """Snaps the active window to the right half of the display."""
        script = '''
        set screenW to 1440
        set screenH to 900
        try
            tell application "Finder"
                set screenBounds to bounds of window of desktop
                set screenW to item 3 of screenBounds
                set screenH to item 4 of screenBounds
            end tell
        on error
            try
                tell application "Finder"
                    set screenBounds to bounds of desktop
                    set screenW to item 3 of screenBounds
                    set screenH to item 4 of screenBounds
                end tell
            end try
        end try
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                if (count of windows of frontApp) > 0 then
                    set frontWin to front window of frontApp
                    set position of frontWin to {screenW / 2, 25}
                    set size of frontWin to {screenW / 2, screenH - 25}
                    return "OK"
                end if
            on error err
                return "ERROR:" & err
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and "OK" in out:
            return "Snapped window to right half."
        return "Could not snap window to right half."

    def center_window(self) -> str:
        """Centers the active window on screen."""
        script = '''
        set screenW to 1440
        set screenH to 900
        try
            tell application "Finder"
                set screenBounds to bounds of window of desktop
                set screenW to item 3 of screenBounds
                set screenH to item 4 of screenBounds
            end tell
        on error
            try
                tell application "Finder"
                    set screenBounds to bounds of desktop
                    set screenW to item 3 of screenBounds
                    set screenH to item 4 of screenBounds
                end tell
            end try
        end try
        tell application "System Events"
            try
                set frontApp to first application process whose frontmost is true
                if (count of windows of frontApp) > 0 then
                    set frontWin to front window of frontApp
                    set targetW to screenW * 0.7
                    set targetH to (screenH - 25) * 0.7
                    set posX to (screenW - targetW) / 2
                    set posY to 25 + ((screenH - 25) - targetH) / 2
                    set position of frontWin to {posX, posY}
                    set size of frontWin to {targetW, targetH}
                    return "OK"
                end if
            on error err
                return "ERROR:" & err
            end try
        end tell
        '''
        success, out = run_multiline_applescript(script)
        if success and "OK" in out:
            return "Centered window."
        return "Could not center window."


    def show_desktop(self) -> str:
        """Shows desktop by activating Finder or triggering Show Desktop shortcut."""
        script = '''
        tell application "Finder" to activate
        tell application "System Events"
            try
                key code 103 -- F11
            on error
                -- Fallback: hide other processes
                set visible of every application process whose frontmost is false to false
            end try
        end tell
        '''
        run_multiline_applescript(script)
        return "Showing desktop."
