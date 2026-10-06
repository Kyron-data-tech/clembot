import re
from pathlib import Path
from typing import Optional, Tuple
from app.core.models import AgentAction, AgentPlan


# Pre-compile the normalize regex (called on every spoken command)
_NORMALIZE_RE = re.compile(r'[^\w\s]')


class FastCommandRouter:
    """
    High-speed deterministic offline command router.
    Resolves standard desktop requests instantly (0ms latency, zero API cost)
    before falling back to AI LLM reasoning.
    """

    _EXACT_MATCHES = None

    @classmethod
    def _get_exact_matches(cls):
        if cls._EXACT_MATCHES is None:
            cls._EXACT_MATCHES = cls._build_exact_matches()
        return cls._EXACT_MATCHES

    @classmethod
    def _build_exact_matches(cls):
        return {
            # Window management
            "minimize the current window": AgentPlan(reply="Minimizing window.", actions=[AgentAction(type="window_minimize")]),
            "minimize this window": AgentPlan(reply="Minimizing window.", actions=[AgentAction(type="window_minimize")]),
            "minimize window": AgentPlan(reply="Minimizing window.", actions=[AgentAction(type="window_minimize")]),
            "maximize the current window": AgentPlan(reply="Maximizing window.", actions=[AgentAction(type="window_maximize")]),
            "maximize this window": AgentPlan(reply="Maximizing window.", actions=[AgentAction(type="window_maximize")]),
            "maximize window": AgentPlan(reply="Maximizing window.", actions=[AgentAction(type="window_maximize")]),
            "restore window": AgentPlan(reply="Restoring window.", actions=[AgentAction(type="window_restore")]),
            "close the current application": AgentPlan(reply="Closing application.", actions=[AgentAction(type="window_close")]),
            "close current window": AgentPlan(reply="Closing window.", actions=[AgentAction(type="window_close")]),
            "close this window": AgentPlan(reply="Closing window.", actions=[AgentAction(type="window_close")]),
            "snap window left": AgentPlan(reply="Snapping window left.", actions=[AgentAction(type="window_snap_left")]),
            "left half": AgentPlan(reply="Moving window left.", actions=[AgentAction(type="window_snap_left")]),
            "snap window right": AgentPlan(reply="Snapping window right.", actions=[AgentAction(type="window_snap_right")]),
            "right half": AgentPlan(reply="Moving window right.", actions=[AgentAction(type="window_snap_right")]),
            "center window": AgentPlan(reply="Centering window.", actions=[AgentAction(type="window_center")]),
            "show desktop": AgentPlan(reply="Showing desktop.", actions=[AgentAction(type="show_desktop")]),

            # System & Media
            "take a screenshot": AgentPlan(reply="Taking screenshot.", actions=[AgentAction(type="screenshot")]),
            "take screenshot": AgentPlan(reply="Taking screenshot.", actions=[AgentAction(type="screenshot")]),
            "screenshot": AgentPlan(reply="Taking screenshot.", actions=[AgentAction(type="screenshot")]),

            # Screen reading / AI vision
            "read the screen": AgentPlan(reply="Reading the screen.", actions=[AgentAction(type="screen_read")]),
            "read screen": AgentPlan(reply="Reading the screen.", actions=[AgentAction(type="screen_read")]),
            "whats on my screen": AgentPlan(reply="Analysing your screen.", actions=[AgentAction(type="screen_read")]),
            "what is on my screen": AgentPlan(reply="Analysing your screen.", actions=[AgentAction(type="screen_read")]),
            "whats on the screen": AgentPlan(reply="Analysing your screen.", actions=[AgentAction(type="screen_read")]),
            "what is on the screen": AgentPlan(reply="Analysing your screen.", actions=[AgentAction(type="screen_read")]),
            "whats on screen": AgentPlan(reply="Analysing your screen.", actions=[AgentAction(type="screen_read")]),
            "what is on screen": AgentPlan(reply="Analysing your screen.", actions=[AgentAction(type="screen_read")]),
            "describe the screen": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "describe my screen": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "describe this screen": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "describe screen": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "describe the display": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "describe my display": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "describe display": AgentPlan(reply="Describing what I see.", actions=[AgentAction(type="screen_read")]),
            "read this": AgentPlan(reply="Reading what's on screen.", actions=[AgentAction(type="screen_read")]),
            "read whats on screen": AgentPlan(reply="Reading the screen.", actions=[AgentAction(type="screen_read")]),
            "read what is on screen": AgentPlan(reply="Reading the screen.", actions=[AgentAction(type="screen_read")]),
            "what does it say": AgentPlan(reply="Reading the screen.", actions=[AgentAction(type="screen_read")]),
            "what does it show": AgentPlan(reply="Looking at the screen.", actions=[AgentAction(type="screen_read")]),
            "analyse the screen": AgentPlan(reply="Analysing the screen.", actions=[AgentAction(type="screen_read")]),
            "analyze the screen": AgentPlan(reply="Analysing the screen.", actions=[AgentAction(type="screen_read")]),
            "capture the screen": AgentPlan(reply="Capturing the screen.", actions=[AgentAction(type="screenshot")]),
            "capture screen": AgentPlan(reply="Capturing the screen.", actions=[AgentAction(type="screenshot")]),
            "capture the display": AgentPlan(reply="Capturing the screen.", actions=[AgentAction(type="screenshot")]),
            "capture display": AgentPlan(reply="Capturing the screen.", actions=[AgentAction(type="screenshot")]),


            "volume up": AgentPlan(reply="Volume up.", actions=[AgentAction(type="volume_up")]),
            "turn volume up": AgentPlan(reply="Volume up.", actions=[AgentAction(type="volume_up")]),
            "volume down": AgentPlan(reply="Volume down.", actions=[AgentAction(type="volume_down")]),
            "turn volume down": AgentPlan(reply="Volume down.", actions=[AgentAction(type="volume_down")]),
            "mute": AgentPlan(reply="Toggling mute.", actions=[AgentAction(type="volume_mute")]),
            "mute volume": AgentPlan(reply="Toggling mute.", actions=[AgentAction(type="volume_mute")]),
            "unmute": AgentPlan(reply="Toggling mute.", actions=[AgentAction(type="volume_mute")]),

            # Clipboard
            "copy this": AgentPlan(reply="Copied.", actions=[AgentAction(type="copy")]),
            "copy": AgentPlan(reply="Copied.", actions=[AgentAction(type="copy")]),
            "paste": AgentPlan(reply="Pasting.", actions=[AgentAction(type="paste")]),
            "paste it": AgentPlan(reply="Pasting.", actions=[AgentAction(type="paste")]),
            "clear clipboard": AgentPlan(reply="Clipboard cleared.", actions=[AgentAction(type="clear_clipboard")]),
            "select all": AgentPlan(reply="Selected all.", actions=[AgentAction(type="select_all")]),
            "undo": AgentPlan(reply="Undone.", actions=[AgentAction(type="undo")]),
            "redo": AgentPlan(reply="Redone.", actions=[AgentAction(type="redo")]),
            "save": AgentPlan(reply="Saved.", actions=[AgentAction(type="save")]),

            # Browser tabs & navigation
            "new tab": AgentPlan(reply="Opening new tab.", actions=[AgentAction(type="browser_new_tab")]),
            "open a new tab": AgentPlan(reply="Opening new tab.", actions=[AgentAction(type="browser_new_tab")]),
            "open new tab": AgentPlan(reply="Opening new tab.", actions=[AgentAction(type="browser_new_tab")]),
            "create a new tab": AgentPlan(reply="Opening new tab.", actions=[AgentAction(type="browser_new_tab")]),
            "create new tab": AgentPlan(reply="Opening new tab.", actions=[AgentAction(type="browser_new_tab")]),
            "close tab": AgentPlan(reply="Closing tab.", actions=[AgentAction(type="vscode_close_file")]),
            "close this tab": AgentPlan(reply="Closing tab.", actions=[AgentAction(type="vscode_close_file")]),
            "close current tab": AgentPlan(reply="Closing current tab.", actions=[AgentAction(type="vscode_close_file")]),
            "close active tab": AgentPlan(reply="Closing active tab.", actions=[AgentAction(type="vscode_close_file")]),
            "close this file": AgentPlan(reply="Closing active file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close the file": AgentPlan(reply="Closing active file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close file": AgentPlan(reply="Closing active file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close active file": AgentPlan(reply="Closing active file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close current file": AgentPlan(reply="Closing active file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close file in vscode": AgentPlan(reply="Closing file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close vscode file": AgentPlan(reply="Closing file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "close file vscode": AgentPlan(reply="Closing file in VS Code.", actions=[AgentAction(type="vscode_close_file")]),
            "next tab": AgentPlan(reply="Next tab.", actions=[AgentAction(type="browser_next_tab")]),
            "switch tab": AgentPlan(reply="Next tab.", actions=[AgentAction(type="browser_next_tab")]),
            "previous tab": AgentPlan(reply="Previous tab.", actions=[AgentAction(type="browser_prev_tab")]),
            "reopen tab": AgentPlan(reply="Reopened tab.", actions=[AgentAction(type="browser_reopen_tab")]),
            "reload": AgentPlan(reply="Reloading.", actions=[AgentAction(type="browser_reload")]),
            "refresh": AgentPlan(reply="Reloading.", actions=[AgentAction(type="browser_reload")]),

            # Browser Search History & Downloads
            "show search history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "show browser search history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "show browser history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "show history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "open search history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "open browser history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "open history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "search history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "browser history": AgentPlan(reply="Opening search history.", actions=[AgentAction(type="browser_show_history")]),
            "show downloads folder": AgentPlan(reply="Opening downloads.", actions=[AgentAction(type="browser_show_downloads")]),
            "show download folder": AgentPlan(reply="Opening downloads.", actions=[AgentAction(type="browser_show_downloads")]),
            "show browser downloads": AgentPlan(reply="Opening downloads.", actions=[AgentAction(type="browser_show_downloads")]),
            "show browser download folder": AgentPlan(reply="Opening downloads.", actions=[AgentAction(type="browser_show_downloads")]),
            "browser downloads": AgentPlan(reply="Opening downloads.", actions=[AgentAction(type="browser_show_downloads")]),
            "open browser downloads": AgentPlan(reply="Opening downloads.", actions=[AgentAction(type="browser_show_downloads")]),

            # Standard Folders
            "open downloads": AgentPlan(reply="Opening Downloads.", actions=[AgentAction(type="open_folder", path="Downloads")]),
            "open my downloads": AgentPlan(reply="Opening Downloads.", actions=[AgentAction(type="open_folder", path="Downloads")]),
            "open my downloads folder": AgentPlan(reply="Opening Downloads.", actions=[AgentAction(type="open_folder", path="Downloads")]),
            "open desktop": AgentPlan(reply="Opening Desktop.", actions=[AgentAction(type="open_folder", path="Desktop")]),
            "open my desktop": AgentPlan(reply="Opening Desktop.", actions=[AgentAction(type="open_folder", path="Desktop")]),
            "open documents": AgentPlan(reply="Opening Documents.", actions=[AgentAction(type="open_folder", path="Documents")]),
            "open my documents": AgentPlan(reply="Opening Documents.", actions=[AgentAction(type="open_folder", path="Documents")]),
            "open my documents folder": AgentPlan(reply="Opening Documents.", actions=[AgentAction(type="open_folder", path="Documents")]),
            "open pictures": AgentPlan(reply="Opening Pictures.", actions=[AgentAction(type="open_folder", path="Pictures")]),
            "open music": AgentPlan(reply="Opening Music.", actions=[AgentAction(type="open_folder", path="Music")]),
            "open videos": AgentPlan(reply="Opening Videos.", actions=[AgentAction(type="open_folder", path="Videos")]),
            "open onedrive": AgentPlan(reply="Opening OneDrive.", actions=[AgentAction(type="open_folder", path="OneDrive")]),
            "open c drive": AgentPlan(reply="Opening C Drive.", actions=[AgentAction(type="open_folder", path="C:\\")]),

            # Windows Shell Targets
            "open file explorer": AgentPlan(reply="Opening File Explorer.", actions=[AgentAction(type="open_app", app="explorer")]),
            "open explorer": AgentPlan(reply="Opening File Explorer.", actions=[AgentAction(type="open_app", app="explorer")]),
            "file explorer": AgentPlan(reply="Opening File Explorer.", actions=[AgentAction(type="open_app", app="explorer")]),
            "explorer": AgentPlan(reply="Opening File Explorer.", actions=[AgentAction(type="open_app", app="explorer")]),
            "open this pc": AgentPlan(reply="Opening This PC.", actions=[AgentAction(type="open_folder", path="::{20D04FE0-3AEA-1069-A2D8-08002B30309D}")]),
            "this pc": AgentPlan(reply="Opening This PC.", actions=[AgentAction(type="open_folder", path="::{20D04FE0-3AEA-1069-A2D8-08002B30309D}")]),
            "open my computer": AgentPlan(reply="Opening This PC.", actions=[AgentAction(type="open_folder", path="::{20D04FE0-3AEA-1069-A2D8-08002B30309D}")]),
            "my computer": AgentPlan(reply="Opening This PC.", actions=[AgentAction(type="open_folder", path="::{20D04FE0-3AEA-1069-A2D8-08002B30309D}")]),
            "open recycle bin": AgentPlan(reply="Opening Recycle Bin.", actions=[AgentAction(type="open_folder", path="::{645FF040-5081-101B-9F08-00AA002F954E}")]),
            "recycle bin": AgentPlan(reply="Opening Recycle Bin.", actions=[AgentAction(type="open_folder", path="::{645FF040-5081-101B-9F08-00AA002F954E}")]),
            "open trash bin": AgentPlan(reply="Opening Recycle Bin.", actions=[AgentAction(type="open_folder", path="::{645FF040-5081-101B-9F08-00AA002F954E}")]),
            "trash bin": AgentPlan(reply="Opening Recycle Bin.", actions=[AgentAction(type="open_folder", path="::{645FF040-5081-101B-9F08-00AA002F954E}")]),
            "open settings": AgentPlan(reply="Opening Windows Settings.", actions=[AgentAction(type="open_url", url="ms-settings:")]),
            "settings": AgentPlan(reply="Opening Windows Settings.", actions=[AgentAction(type="open_url", url="ms-settings:")]),
            "open windows settings": AgentPlan(reply="Opening Windows Settings.", actions=[AgentAction(type="open_url", url="ms-settings:")]),
            "windows settings": AgentPlan(reply="Opening Windows Settings.", actions=[AgentAction(type="open_url", url="ms-settings:")]),
            "open task manager": AgentPlan(reply="Opening Task Manager.", actions=[AgentAction(type="open_app", app="taskmgr")]),
            "task manager": AgentPlan(reply="Opening Task Manager.", actions=[AgentAction(type="open_app", app="taskmgr")]),
            "open control panel": AgentPlan(reply="Opening Control Panel.", actions=[AgentAction(type="open_app", app="control")]),
            "control panel": AgentPlan(reply="Opening Control Panel.", actions=[AgentAction(type="open_app", app="control")]),

            # VS Code
            "run this python program": AgentPlan(reply="Running Python program.", actions=[AgentAction(type="vscode_run_code")]),
            "run this python file": AgentPlan(reply="Running Python file.", actions=[AgentAction(type="vscode_run_code")]),
            "run code": AgentPlan(reply="Running code.", actions=[AgentAction(type="vscode_run_code")]),
            "undo code change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo the code change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo the change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo last change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo the last change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo the edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo last edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "undo the last edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert the change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert code change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert the code change": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert the edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert last edit": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "revert that": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
            "change it back": AgentPlan(reply="Reverting last code change.", actions=[AgentAction(type="vscode_undo")]),
        }

    def plan_for_command(self, raw_command: str, llm_active: bool = False) -> Optional[AgentPlan]:
        cmd = raw_command.strip()
        lower = cmd.lower()
        normalized = _NORMALIZE_RE.sub('', lower).strip()

        # 1. Exact static commands lookup (O(1) cached singleton, zero per-call allocation)
        exact_matches = self._get_exact_matches()
        if normalized in exact_matches:
            return exact_matches[normalized]

        # Code Undo / Revert patterns — matches everything not caught by exact_matches above
        undo_code_match = re.search(
            r'^(?:'
            r'(?:please\s+)?(?:undo|revert)(?:\s+(?:the|that|this|my|it))?(?:\s+(?:last|previous))?(?:\s+(?:code\s+)?(?:change|edit|modification)s?)?'
            r'|change\s+it\s+back'
            r'|take\s+it\s+back'
            r'|put\s+it\s+back'
            r')[.!?]*$',
            lower
        )
        if undo_code_match and lower.strip(".!? "):
            return AgentPlan(
                reply="Reverting last code change.",
                actions=[AgentAction(type="vscode_undo")]
            )

        # 1b. Browser Tabs & History Patterns (Chrome & Brave)
        tab_num_map = {
            "one": 1, "first": 1, "1st": 1,
            "two": 2, "second": 2, "2nd": 2,
            "three": 3, "third": 3, "3rd": 3,
            "four": 4, "fourth": 4, "4th": 4,
            "five": 5, "fifth": 5, "5th": 5,
            "six": 6, "sixth": 6, "6th": 6,
            "seven": 7, "seventh": 7, "7th": 7,
            "eight": 8, "eighth": 8, "8th": 8,
            "nine": 9, "ninth": 9, "9th": 9,
            "ten": 10, "tenth": 10, "10th": 10,
        }

        # Browser switch tab number (e.g. "open tab number 4", "switch to tab 4", "fourth tab", "in brave open tab number 4")
        tab_match = (
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?(?:open|switch\s+to|go\s+to)\s+(?:the\s+)?tab(?:\s+number)?\s+(\w+)(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower) or
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?tab(?:\s+number)?\s+(\w+)(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower) or
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?(?:(?:open|switch\s+to|go\s+to)\s+)?(?:the\s+)?(\w+)\s+tab(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower)
        )
        if tab_match:
            groups = tab_match.groups()
            b_name = tab_match.group(1) if tab_match.group(1) in ['chrome', 'brave'] else None
            if not b_name and len(groups) >= 3 and tab_match.group(3) in ['chrome', 'brave']:
                b_name = tab_match.group(3)
            raw_token = tab_match.group(2) if len(groups) >= 2 and tab_match.group(2) else ''
            if not raw_token or raw_token in ['chrome', 'brave']:
                raw_token = tab_match.group(1)
            t_num = int(raw_token) if (raw_token and raw_token.isdigit()) else tab_num_map.get((raw_token or "").lower())
            if t_num and t_num >= 1:
                reply_browser = f" in {b_name.capitalize()}" if b_name else ""
                return AgentPlan(
                    reply=f"Opening tab {t_num}{reply_browser}.",
                    actions=[AgentAction(type="browser_switch_tab_number", amount=t_num, app=b_name)]
                )

        # Browser New Tab
        new_tab_match = (
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?(?:open|create|launch)\s+(?:a\s+)?new\s+tab(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower) or
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?new\s+tab(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower)
        )
        if new_tab_match:
            b_name = new_tab_match.group(1) or (new_tab_match.group(2) if len(new_tab_match.groups()) >= 2 else None)
            reply_name = f" in {b_name.capitalize()}" if b_name else ""
            return AgentPlan(
                reply=f"Opening new tab{reply_name}.",
                actions=[AgentAction(type="browser_new_tab", app=b_name)]
            )

        # Browser Search History
        history_match = (
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?(?:show|open|display)\s+(?:the\s+)?(?:browser\s+)?(?:search\s+)?history(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower) or
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?(?:browser\s+)?search\s+history(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower) or
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?browser\s+history(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower)
        )
        if history_match:
            b_name = history_match.group(1) or (history_match.group(2) if len(history_match.groups()) >= 2 else None)
            reply_name = f" in {b_name.capitalize()}" if b_name else ""
            return AgentPlan(
                reply=f"Opening search history{reply_name}.",
                actions=[AgentAction(type="browser_show_history", app=b_name)]
            )

        # Browser Downloads Folder
        downloads_match = (
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?(?:show|open|display)\s+(?:the\s+)?(?:browser\s+)?downloads?(?:\s+folder)?(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower) or
            re.search(r'^(?:(?:in|on)\s+(chrome|brave)\s+)?browser\s+downloads?(?:\s+folder)?(?:\s+(?:in|on)\s+(chrome|brave))?[.!?]*$', lower)
        )
        if downloads_match:
            b_name = downloads_match.group(1) or (downloads_match.group(2) if len(downloads_match.groups()) >= 2 else None)
            reply_name = f" in {b_name.capitalize()}" if b_name else ""
            return AgentPlan(
                reply=f"Opening downloads{reply_name}.",
                actions=[AgentAction(type="browser_show_downloads", app=b_name)]
            )

        # 1c. Screen Capture & Screen Reading Patterns
        # e.g. "take a screenshot of the display", "capture the screen", "capture display"
        screenshot_match = (
            re.search(
                r'^(?:please\s+)?(?:take|capture)\s+(?:a\s+)?(?:screenshot|screen\s*shot|snapshot|pic|picture)(?:\s+(?:of|on)\s+(?:the\s+)?(?:screen|display|desktop))?[.!?]*$',
                lower
            ) or
            re.search(
                r'^(?:please\s+)?(?:take|capture)\s+(?:the\s+)?(?:screen|display|desktop)[.!?]*$',
                lower
            )
        )
        if screenshot_match:
            return AgentPlan(
                reply="Taking screenshot.",
                actions=[AgentAction(type="screenshot")]
            )

        # e.g. "read the screen", "describe the display", "what is displayed on the screen", "what is on my display"
        screen_read_match = (
            re.search(r'^(?:please\s+)?(?:read|describe|explain|see|analyse|analyze)\s+(?:what(?:[\'\s]s|\s+is)\s+(?:on|in)\s+)?(?:the|my|this)?\s*(?:screen|display)[.!?]*$', lower) or
            re.search(r'^(?:what(?:[\'\s]s|\s+is)\s+)(?:on|in)\s+(?:the|my|this)?\s*(?:screen|display)[.!?]*$', lower) or
            re.search(r'^(?:what(?:[\'\s]s|\s+is)\s+)?(?:displayed|open|shown|visible)\s+(?:on|in)?\s*(?:the|my|this)?\s*(?:screen|display)[.!?]*$', lower) or
            re.search(r'^(?:what\s+(?:application|app|file|folder|window)\s+is\s+)?(?:displayed|open|shown|visible)\s+(?:on|in)?\s*(?:the|my|this)?\s*(?:screen|display)[.!?]*$', lower) or
            re.search(r'^what\s+do\s+you\s+see(?:\s+on\s+(?:the|my|this)?\s*(?:screen|display))?[.!?]*$', lower)
        )
        if screen_read_match:
            return AgentPlan(
                reply="Reading the screen.",
                actions=[AgentAction(type="screen_read")]
            )

        # 2. Directory inspection / What's inside?
        # e.g. "What files are in Downloads?", "What is inside Downloads?", "Show me the files in this folder"
        list_match = re.search(r'^(?:what(?:s|\s+is|\s+files\s+are)\s+(?:in|inside)|show(?:\s+me)?\s+(?:the\s+)?files\s+in)\s+(.*?)[?.!]*$', cmd, re.IGNORECASE)
        if list_match:
            target_folder = list_match.group(1).strip()
            return AgentPlan(
                reply="Checking directory contents.",
                actions=[AgentAction(type="list_directory", path=target_folder)]
            )

        # 3. Create folder
        # e.g. "Create a new folder called Projects on Desktop", "Create a folder called AI Projects"
        create_folder_match = re.search(r'^create\s+(?:a\s+)?(?:new\s+)?folder\s+(?:called|named)\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if create_folder_match:
            folder_spec = create_folder_match.group(1).strip()
            return AgentPlan(
                reply=f"Creating folder {folder_spec}.",
                actions=[AgentAction(type="create_folder", path=folder_spec)]
            )

        # 4. Create file
        # e.g. "Create a file called notes.txt", "Create a new Python file"
        create_file_match = re.search(r'^create\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?file\s+(?:called|named)\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if create_file_match:
            file_name = create_file_match.group(1).strip()
            return AgentPlan(
                reply=f"Creating file {file_name}.",
                actions=[AgentAction(type="create_file", path=file_name)]
            )
        if normalized in ["create a new python file", "create new python file"]:
            return AgentPlan(
                reply="Creating main.py.",
                actions=[AgentAction(type="create_file", path="main.py")]
            )

        # 5. Rename file / folder
        # e.g. "Rename this file to resume.pdf", "Rename notes.txt to college_notes.txt"
        rename_match = re.search(r'^rename\s+(?:this\s+file|file|folder)?\s*(.*?)\s+to\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if rename_match:
            src = rename_match.group(1).strip() or "this file"
            dst = rename_match.group(2).strip()
            return AgentPlan(
                reply=f"Renaming to {dst}.",
                actions=[AgentAction(type="rename_path", path=src, destination=dst)]
            )

        # 6. Delete file / folder
        # e.g. "Delete this folder", "Delete college_notes.txt", "Delete my Downloads folder"
        delete_match = re.search(r'^delete\s+(?:this\s+folder|this\s+file|file|folder)?\s*(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if delete_match:
            target = delete_match.group(1).strip() or "this"
            return AgentPlan(
                reply=f"Preparing to delete {target}.",
                actions=[AgentAction(type="trash_path", path=target)]
            )

        # 7. Move file / folder
        # e.g. "Move this file to Downloads", "Move college_notes.txt to Desktop", "Move the resume from Downloads to Documents"
        move_from_to = re.search(r'^move\s+(?:the\s+)?(.*?)\s+from\s+(.*?)\s+to\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if move_from_to:
            item = move_from_to.group(1).strip()
            src_folder = move_from_to.group(2).strip()
            dst_folder = move_from_to.group(3).strip()
            full_src = f"{item} in {src_folder}"
            return AgentPlan(
                reply=f"Moving {item} to {dst_folder}.",
                actions=[AgentAction(type="move_path", path=full_src, destination=dst_folder)]
            )
        move_simple = re.search(r'^move\s+(.*?)\s+to\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if move_simple:
            src = move_simple.group(1).strip()
            dst = move_simple.group(2).strip()
            return AgentPlan(
                reply=f"Moving {src} to {dst}.",
                actions=[AgentAction(type="move_path", path=src, destination=dst)]
            )

        # 8. Copy file / folder
        # e.g. "Copy this file", "Copy this folder to Desktop", "Copy college_notes.txt"
        copy_to_match = re.search(r'^copy\s+(.*?)\s+to\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if copy_to_match:
            src = copy_to_match.group(1).strip()
            dst = copy_to_match.group(2).strip()
            return AgentPlan(
                reply=f"Copying {src} to {dst}.",
                actions=[AgentAction(type="copy_path", path=src, destination=dst)]
            )
        copy_single = re.search(r'^copy\s+(?:file\s+|folder\s+)?(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if copy_single and copy_single.group(1).strip().lower() not in ["this", "it"]:
            src = copy_single.group(1).strip()
            return AgentPlan(
                reply=f"Copying {src}.",
                actions=[AgentAction(type="copy_path", path=src)]
            )

        # 9. Find / Search files
        # e.g. "Find my resume", "Find all Python files in my project"
        find_match = re.search(r'^(?:find|search\s+for)\s+(?:my\s+|a\s+)?(resume|file\s+.*|files\s+.*|.*\.py|.*\.pdf|.*\.docx?|.*\.txt)[.!?]*$', cmd, re.IGNORECASE)
        if find_match:
            query = find_match.group(1).strip()
            return AgentPlan(
                reply=f"Searching for {query}.",
                actions=[AgentAction(type="find_file", query=query)]
            )

        # 10. Folders, Drives, and Files
        # Drive root: e.g. "Open C drive", "Open F drive", "Open drive D"
        drive_match = re.search(r'^(?:open|show)\s+(?:drive\s+)?([a-zA-Z])(?::|\s+drive)?[.!?]*$', lower)
        if drive_match:
            d_letter = drive_match.group(1).upper()
            return AgentPlan(
                reply=f"Opening {d_letter} Drive.",
                actions=[AgentAction(type="open_folder", path=f"{d_letter}:\\")]
            )

        # Known standard folders with/without "folder" suffix
        # e.g. "open downloads", "open my downloads folder", "open desktop folder"
        known_folder_match = re.search(r'^(?:open|show)(?:\s+my)?\s+(downloads|desktop|documents|pictures|music|videos|onedrive)(?:\s+folder|\s+directory)?[.!?]*$', lower)
        if known_folder_match:
            f_name = known_folder_match.group(1).capitalize()
            return AgentPlan(
                reply=f"Opening {f_name}.",
                actions=[AgentAction(type="open_folder", path=f_name)]
            )

        # Open in VS Code explicit directive
        open_in_vscode = re.search(r'^(?:open|launch)\s+(.*?)\s+(?:in|inside|on)\s+vs\s*code[.!?]*$', cmd, re.IGNORECASE) or \
                         re.search(r'^(?:open|launch)\s+(?:in|inside|on)\s+vs\s*code\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if open_in_vscode:
            raw_target = open_in_vscode.group(1).strip().strip("'\" ")
            clean_tgt = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', raw_target, flags=re.IGNORECASE).strip()
            clean_tgt = re.sub(r'\s+(?:folder|directory|project|workspace|file)$', '', clean_tgt, flags=re.IGNORECASE).strip() or raw_target
            clean_tgt = clean_tgt.strip("'\" ")
            display_name = clean_tgt
            target_path = clean_tgt
            try:
                from app.platform_layer.factory import platform_adapter
                resolved = platform_adapter.resolve_spoken_path(clean_tgt)
                if resolved and resolved.exists():
                    display_name = resolved.name
                elif "\\" in clean_tgt or "/" in clean_tgt:
                    display_name = Path(clean_tgt).name or clean_tgt
                elif clean_tgt.split():
                    display_name = clean_tgt.split()[-1]
            except Exception:
                display_name = Path(clean_tgt).name or clean_tgt
            return AgentPlan(
                reply=f"Opening {display_name} in VS Code.",
                actions=[AgentAction(type="vscode_open_file", path=target_path)]
            )

        # Tab / File switching: "open next file", "next file", "switch file", "previous file"
        next_file_m = re.search(r'^(?:open\s+)?(?:the\s+)?(?:next|other|another)\s+file(?:\s+in\s+vscode)?[.!?]*$', lower) or \
                      re.search(r'^(?:switch\s+(?:to\s+)?(?:next\s+)?file|switch\s+tab|next\s+tab|next\s+file)[.!?]*$', lower)
        if next_file_m:
            return AgentPlan(
                reply="Switching to next file in VS Code.",
                actions=[AgentAction(type="vscode_next_file")]
            )

        prev_file_m = re.search(r'^(?:open\s+)?(?:the\s+)?(?:previous|prev)\s+file(?:\s+in\s+vscode)?[.!?]*$', lower) or \
                      re.search(r'^(?:switch\s+(?:to\s+)?(?:previous|prev)\s+file|prev\s+tab|previous\s+tab)[.!?]*$', lower)
        if prev_file_m:
            return AgentPlan(
                reply="Switching to previous file in VS Code.",
                actions=[AgentAction(type="vscode_prev_file")]
            )

        # Explicit folder: e.g. "open folder projects", "open the folder voiceps", "open practical folder"
        explicit_folder = re.search(r'^(?:open|show)\s+(?:the\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?(.*?)[.!?]*$', cmd, re.IGNORECASE) or \
                          re.search(r'^(?:open|show)\s+(?:the\s+)?(.*?)\s+(?:folder|directory)[.!?]*$', cmd, re.IGNORECASE)
        if explicit_folder:
            f_name = explicit_folder.group(1).strip().strip("'\" ")
            clean_f = re.sub(r'^(?:(?:the|my)\s+)?(?:folder|directory|project|workspace)\s+', '', f_name, flags=re.IGNORECASE).strip() or f_name
            clean_f = clean_f.strip("'\" ")
            display_name = clean_f
            target_path = clean_f
            try:
                from app.platform_layer.factory import platform_adapter
                resolved = platform_adapter.resolve_spoken_path(clean_f)
                if resolved and resolved.exists():
                    display_name = resolved.name
                elif "\\" in clean_f or "/" in clean_f:
                    display_name = Path(clean_f).name or clean_f
                elif clean_f.split():
                    display_name = clean_f.split()[-1]
            except Exception:
                display_name = Path(clean_f).name or clean_f
            return AgentPlan(
                reply=f"Opening folder {display_name}.",
                actions=[AgentAction(type="open_folder", path=target_path)]
            )

        # Explicit file: e.g. "open file notes.txt", "open the file resume.pdf", "open my file"
        explicit_file = re.search(r'^(?:open|show)\s+(?:the\s+)?file\s+(?:called\s+|named\s+)?(.*?)[.!?]*$', cmd, re.IGNORECASE) or \
                        re.search(r'^(?:open|show)\s+(?:the\s+)?(.*?\s+file)[.!?]*$', cmd, re.IGNORECASE)
        if explicit_file:
            f_name = explicit_file.group(1).strip()
            norm_f = f_name.lower().strip()
            if norm_f in ["next", "other", "another", "next file", "other file", "another file"]:
                return AgentPlan(reply="Switching to next file in VS Code.", actions=[AgentAction(type="vscode_next_file")])
            if norm_f in ["previous", "prev", "previous file", "prev file"]:
                return AgentPlan(reply="Switching to previous file in VS Code.", actions=[AgentAction(type="vscode_prev_file")])
            # Intercept shell targets if spoken as "open file explorer" etc.
            if norm_f in ["explorer", "file explorer"]:
                return AgentPlan(reply="Opening File Explorer.", actions=[AgentAction(type="open_app", app="explorer")])
            if norm_f in ["this pc", "my computer"]:
                return AgentPlan(reply="Opening This PC.", actions=[AgentAction(type="open_folder", path="::{20D04FE0-3AEA-1069-A2D8-08002B30309D}")])
            if norm_f in ["recycle bin", "trash bin"]:
                return AgentPlan(reply="Opening Recycle Bin.", actions=[AgentAction(type="open_folder", path="::{645FF040-5081-101B-9F08-00AA002F954E}")])
            if norm_f in ["settings", "windows settings"]:
                return AgentPlan(reply="Opening Windows Settings.", actions=[AgentAction(type="open_url", url="ms-settings:")])
            if norm_f in ["task manager", "taskmgr"]:
                return AgentPlan(reply="Opening Task Manager.", actions=[AgentAction(type="open_app", app="taskmgr")])

            return AgentPlan(
                reply=f"Opening file {f_name}.",
                actions=[AgentAction(type="open_file", path=f_name)]
            )

        # Files with extensions: e.g. "open notes.txt", "open report.pdf", "open script.py", "open class,object.py"
        # Generic: match ANY extension (1-6 alphanumeric chars) — this is safe because by this
        # point known folder names and app names have already been handled above.
        file_ext_match = re.search(r'^open\s+([\w\-., ()]+\.[a-zA-Z0-9]{1,6})[.!?]*$', cmd, re.IGNORECASE)
        if file_ext_match:
            f_target = file_ext_match.group(1).strip()
            return AgentPlan(
                reply=f"Opening {f_target}.",
                actions=[AgentAction(type="open_file", path=f_target)]
            )

        # 11. Web search, YouTube, and Informational Questions
        # e.g. "Search Google for Python Django tutorials", "Open YouTube and search for Python DSA"
        yt_search = re.search(r'^(?:open\s+youtube\s+and\s+search\s+for|search\s+youtube\s+for)\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if yt_search:
            q = yt_search.group(1).strip()
            return AgentPlan(
                reply=f"Searching YouTube for {q}.",
                actions=[AgentAction(type="web_search", query=q, scope="youtube")]
            )

        google_search = re.search(r'^(?:search\s+google\s+for|google|search\s+the\s+web\s+for|search\s+for)\s+(.*?)[.!?]*$', cmd, re.IGNORECASE)
        if google_search:
            q = google_search.group(1).strip()
            return AgentPlan(
                reply=f"Searching Google for {q}.",
                actions=[AgentAction(type="web_search", query=q, scope="google")]
            )

        # Informational questions & tell me queries
        # e.g. "tell distance from satna to jabalpur", "tell me what is the weather", "what is machine learning", "distance from satna to jabalpur"
        question_pattern = re.search(
            r'^(?:tell(?:\s+me)?(?:\s+about|\s+the)?|what\s+is|whats|who\s+is|whos|where\s+is|wheres|how\s+(?:to|far|much|many|is|do|does|can)|distance\s+(?:from|between)|why\s+is|why\s+do|when\s+is|when\s+was)\s+(.*?)[.?]*$',
            cmd,
            re.IGNORECASE
        )
        # If an LLM (Gemini or Ollama) is active, do NOT intercept questions here;
        # let them pass through to the LLM for conversational open-ended speech!
        # If no LLM is active (heuristic offline mode), route to browser Google search.
        if question_pattern and not llm_active:
            return AgentPlan(
                reply=f"Searching for {cmd}.",
                actions=[AgentAction(type="web_search", query=cmd, scope="google")]
            )

        # 12. Code Editor / VS Code navigation & line jumps
        # e.g. "Open app.py in VS Code", "Open my Django project in VS Code", "Go to line 25"
        # 12. Code Editor / VS Code navigation & line jumps
        # e.g. "Open app.py in VS Code", "Open my Django project in VS Code", "Go to line 25", "jump to line thirty six"
        jump_line = re.search(r'^(?:go\s+to|jump\s+to|navigate\s+to)\s+line\s+(.+?)[.!?]*$', cmd, re.IGNORECASE)
        if jump_line:
            from app.editor.code_edit_parser import _parse_line_number
            line_num = _parse_line_number(jump_line.group(1).strip())
            if line_num:
                return AgentPlan(
                    reply=f"Going to line {line_num}.",
                    actions=[AgentAction(type="vscode_jump_line", line_number=line_num)]
                )


        # 13. Code editing & reading — all patterns handled by CodeEditParser
        # Examples:
        #   "in line 6 replace char with int"
        #   "on line 6 change the variable name x to counter"
        #   "replace line 4 with x = 0"
        #   "delete line 10"
        #   "delete lines 5 to 8"
        #   "insert print hello after line 5"
        #   "add x = 0 before line 3"
        #   "comment out line 7"
        #   "uncomment line 7"
        #   "rename function foo to bar"
        #   "add try except at line 12"
        #   "read line 6" / "show me line 6" / "what is on line 6" / "show line 36"
        #   "save this file"

        # Read / show a single line with optional file:
        # e.g. "show line 36", "shoreline 22", "show me line thirty six", "read line 10 in main.py"
        read_line_with_file = re.search(
            r'^(?:read(?:\s+me)?|show(?:\s+me)?|shoreline|showline|sureline|display|view|what(?:\'s|\s+is)\s+(?:on|at))\s+(?:line\s+)?(.+?)\s+in\s+([^\s]+\.[a-zA-Z0-9]{1,6})[.!?]*$',
            cmd, re.IGNORECASE
        )
        if read_line_with_file:
            from app.editor.code_edit_parser import _parse_line_number
            ln = _parse_line_number(read_line_with_file.group(1).strip())
            target_f = read_line_with_file.group(2).strip()
            if ln:
                verb_reply = "Showing" if re.search(r'\b(?:show|display|view|shoreline|showline)\b', lower) else "Reading"
                return AgentPlan(
                    reply=f"{verb_reply} line {ln} of {target_f}.",
                    actions=[AgentAction(type="vscode_read_line", line_number=ln, path=target_f)]
                )

        read_line = re.search(
            r'^(?:read(?:\s+me)?|show(?:\s+me)?|shoreline|showline|sureline|display|view|what(?:\'s|\s+is)\s+(?:on|at))\s+(?:line\s+)?(.+?)[.!?]*$',
            cmd, re.IGNORECASE
        )
        if read_line:
            from app.editor.code_edit_parser import _parse_line_number
            ln = _parse_line_number(read_line.group(1).strip())
            if ln:
                verb_reply = "Showing" if re.search(r'\b(?:show|display|view|shoreline|showline)\b', lower) else "Reading"
                return AgentPlan(
                    reply=f"{verb_reply} line {ln}.",
                    actions=[AgentAction(type="vscode_read_line", line_number=ln)]
                )

        # Save this file — matches:
        #   "save" / "save this file" / "save the file" / "save file"
        #   "save the file main.py" / "save this code" / "save my work"
        save_file = re.search(
            r'^save(?:\s+(?:this|the|my))?(?:\s+(?:file|code|document|work))?(?:\s+\S+)?[.!?]*$',
            cmd, re.IGNORECASE
        )
        if save_file and lower.startswith("save"):
            return AgentPlan(reply="Saving file.", actions=[AgentAction(type="save")])

        # Delegate to CodeEditParser for all structured edits
        from app.editor.code_edit_parser import parse_voice_edit
        parsed = parse_voice_edit(cmd)
        if parsed:
            return AgentPlan(
                reply=parsed.summary,
                actions=[AgentAction(
                    type="vscode_edit",
                    text=parsed.token,
                    line_number=parsed.line_number or None
                )]
            )

        # 14. Project / Workspace Opening
        # e.g. "Open my Django project", "Open project voiceps", "Open project practical"
        open_proj = re.search(r'^(?:open|launch)\s+(?:my\s+)?(.*?)\s+(?:project|workspace|repository|repo)[.!?]*$', lower) or \
                    re.search(r'^(?:open|launch)\s+(?:my\s+)?(?:project|workspace|repository|repo)\s+(.*?)[.!?]*$', lower)
        if open_proj:
            proj_name = open_proj.group(1).strip()
            if llm_active:
                # Allow LLM with full context to locate the workspace and open it
                return None
            return AgentPlan(
                reply=f"Opening {proj_name}.",
                actions=[AgentAction(type="open_folder", path=proj_name)]
            )

        # Direct file or folder path with drive letter (e.g. "open C:\Users\amrat\Desktop\practice\python", "open D:/projects/main.py")
        abs_path_match = re.search(r'^(?:open|launch|show)\s+(?:(?:the|my)\s+)?(?:file|folder|directory)?\s*([a-zA-Z]:[\\/][^\s].*?)[.!?]*$', cmd, re.IGNORECASE)
        if abs_path_match:
            raw_p = abs_path_match.group(1).strip().strip("'\" ")
            clean_p = re.sub(r'\s+(?:folder|directory|project|workspace|file)$', '', raw_p, flags=re.IGNORECASE).strip() or raw_p
            clean_p = clean_p.strip("'\" ")
            p_obj = Path(clean_p)
            disp_name = p_obj.name or clean_p
            if p_obj.exists():
                if p_obj.is_dir():
                    return AgentPlan(reply=f"Opening folder {disp_name}.", actions=[AgentAction(type="open_folder", path=clean_p)])
                else:
                    return AgentPlan(reply=f"Opening {disp_name}.", actions=[AgentAction(type="open_file", path=clean_p)])
            else:
                has_ext = bool(re.search(r'\.[a-zA-Z0-9]{1,6}$', clean_p))
                act = "open_file" if has_ext else "open_folder"
                rep_type = "file" if has_ext else "folder"
                return AgentPlan(reply=f"Opening {rep_type} {disp_name}.", actions=[AgentAction(type=act, path=clean_p)])

        # 15. App launching & intelligent opening
        # e.g. "Open Chrome", "Open Edge", "Open VS Code", "Open Notepad", "Open Calculator"
        open_app = re.search(r'^(?:open|launch|start|switch\s+to)\s+(.*?)$', lower)
        if open_app:
            target_app = open_app.group(1).strip()
            # Skip if target looks like conversational instruction or file
            if target_app.startswith(("this ", "the ", "that ")) and any(w in target_app for w in ["function", "class", "method", "variable", "line", "error", "bug"]):
                return None
            # If target looks like a website
            if target_app.startswith(("http://", "https://", "www.")) or target_app in ["github", "youtube", "gmail", "docs", "sheets", "chatgpt", "gemini", "claude", "reddit", "whatsapp web"]:
                return AgentPlan(
                    reply=f"Opening {target_app}.",
                    actions=[AgentAction(type="open_url", url=target_app)]
                )
            return AgentPlan(
                reply=f"Opening {target_app}.",
                actions=[AgentAction(type="open_app", app=target_app)]
            )

        # 16. Close file / editor tab
        # e.g. "close this file", "close file in vscode", "close main.py", "close file calc.py"
        close_file_explicit = re.search(
            r'^(?:close|quit|exit)\s+(?:the\s+|this\s+|current\s+|active\s+)?(?:file|document)(?:\s+(?:in|on|from)\s+vscode)?(?:\s+(?:named|called)\s+(.*?))?$',
            lower
        )
        if close_file_explicit:
            named = close_file_explicit.group(1)
            target = named.strip() if named else None
            return AgentPlan(
                reply=f"Closing {target or 'active file'} in VS Code.",
                actions=[AgentAction(type="vscode_close_file", path=target)]
            )

        close_named_file = re.search(
            r'^(?:close|quit|exit)\s+(?:file\s+)?([a-zA-Z0-9_\-]+\.[a-zA-Z0-9]{1,5})$',
            lower
        )
        if close_named_file:
            fname = close_named_file.group(1).strip()
            return AgentPlan(
                reply=f"Closing {fname} in VS Code.",
                actions=[AgentAction(type="vscode_close_file", path=fname)]
            )

        close_vsc_file = re.search(
            r'^(?:close|quit|exit)\s+(?:vscode\s+file|file\s+vscode|file\s+in\s+vscode|active\s+editor)$',
            lower
        )
        if close_vsc_file:
            return AgentPlan(
                reply="Closing file in VS Code.",
                actions=[AgentAction(type="vscode_close_file")]
            )

        # 17. Close app
        # e.g. "Close Chrome", "Close Notepad", "Close VS Code"
        close_app = re.search(r'^(?:close|quit|exit)\s+(.*?)$', lower)
        if close_app:
            target_app = close_app.group(1).strip()

            # Vague / context-dependent targets → close the foreground window (Alt+F4)
            _VAGUE_CLOSE = {
                "it", "this", "that", "app", "application", "the app",
                "the application", "window", "the window", "current window",
                "active window", "this app", "that app", "current app",
                "active app", "the current app", "the active app",
                "current application", "active application",
            }
            if target_app in _VAGUE_CLOSE:
                return AgentPlan(
                    reply="Closing the current window.",
                    actions=[AgentAction(type="window_close")]
                )

            # If target looks like a file name
            if re.search(r'\.[a-zA-Z0-9]{1,5}$', target_app):
                return AgentPlan(
                    reply=f"Closing {target_app} in VS Code.",
                    actions=[AgentAction(type="vscode_close_file", path=target_app)]
                )
            if target_app in ["this file", "the file", "file", "current file", "active file", "file in vscode", "vscode file", "file vscode"]:
                return AgentPlan(
                    reply="Closing file in VS Code.",
                    actions=[AgentAction(type="vscode_close_file")]
                )
            return AgentPlan(
                reply=f"Closing {target_app}.",
                actions=[AgentAction(type="close_app", app=target_app)]
            )

        return None
