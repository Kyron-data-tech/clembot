"""
tests/test_browser_commands.py

Unit tests for browser-context commands:
  1. FastCommandRouter routing — new tab, tab N, history, downloads
  2. BrowserController.get_displayed_browser — chrome/brave detection
  3. BrowserController methods — guarded by browser presence check
"""
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from app.commands.fast_router import FastCommandRouter
from app.core.models import AgentAction, AgentPlan


# ── 1. FastCommandRouter routing ─────────────────────────────────────────────

class TestBrowserFastRouterExactMatches(unittest.TestCase):
    def setUp(self):
        self.router = FastCommandRouter()

    def _plan(self, cmd: str) -> AgentPlan:
        p = self.router.plan_for_command(cmd)
        self.assertIsNotNone(p, msg=f"No plan for: {cmd!r}")
        return p

    def _action_type(self, cmd: str) -> str:
        return self._plan(cmd).actions[0].type

    # ── New tab exact matches ──
    def test_new_tab_exact(self):
        self.assertEqual(self._action_type("new tab"), "browser_new_tab")

    def test_open_a_new_tab_exact(self):
        self.assertEqual(self._action_type("open a new tab"), "browser_new_tab")

    def test_open_new_tab_exact(self):
        self.assertEqual(self._action_type("open new tab"), "browser_new_tab")

    def test_create_a_new_tab_exact(self):
        self.assertEqual(self._action_type("create a new tab"), "browser_new_tab")

    # ── Search history exact matches ──
    def test_show_search_history_exact(self):
        self.assertEqual(self._action_type("show search history"), "browser_show_history")

    def test_show_browser_history_exact(self):
        self.assertEqual(self._action_type("show browser history"), "browser_show_history")

    def test_open_browser_history_exact(self):
        self.assertEqual(self._action_type("open browser history"), "browser_show_history")

    def test_search_history_exact(self):
        self.assertEqual(self._action_type("search history"), "browser_show_history")

    def test_browser_history_exact(self):
        self.assertEqual(self._action_type("browser history"), "browser_show_history")

    # ── Downloads folder exact matches ──
    def test_show_downloads_folder_exact(self):
        self.assertEqual(self._action_type("show downloads folder"), "browser_show_downloads")

    def test_show_browser_downloads_exact(self):
        self.assertEqual(self._action_type("show browser downloads"), "browser_show_downloads")

    def test_browser_downloads_exact(self):
        self.assertEqual(self._action_type("browser downloads"), "browser_show_downloads")


class TestBrowserFastRouterRegexMatches(unittest.TestCase):
    def setUp(self):
        self.router = FastCommandRouter()

    def _action_of(self, cmd: str) -> AgentAction:
        p = self.router.plan_for_command(cmd)
        self.assertIsNotNone(p, msg=f"No plan for: {cmd!r}")
        self.assertTrue(len(p.actions) > 0, msg=f"No actions for: {cmd!r}")
        return p.actions[0]

    # ── Tab number routing ──
    def test_open_tab_number_4(self):
        a = self._action_of("open tab number 4")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)

    def test_open_tab_4(self):
        a = self._action_of("open tab 4")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)

    def test_switch_to_tab_4(self):
        a = self._action_of("switch to tab 4")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)

    def test_fourth_tab(self):
        a = self._action_of("fourth tab")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)

    def test_open_tab_number_four(self):
        a = self._action_of("open tab number four")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)

    def test_tab_4(self):
        a = self._action_of("tab 4")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)

    def test_in_brave_open_tab_number_4(self):
        a = self._action_of("in brave open tab number 4")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)
        self.assertEqual(a.app, "brave")

    def test_open_tab_4_in_chrome(self):
        a = self._action_of("open tab 4 in chrome")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 4)
        self.assertEqual(a.app, "chrome")

    def test_second_tab(self):
        a = self._action_of("second tab")
        self.assertEqual(a.type, "browser_switch_tab_number")
        self.assertEqual(a.amount, 2)

    # ── New tab via regex ──
    def test_in_chrome_open_a_new_tab(self):
        a = self._action_of("in chrome open a new tab")
        self.assertEqual(a.type, "browser_new_tab")
        self.assertEqual(a.app, "chrome")

    def test_open_a_new_tab_in_brave(self):
        a = self._action_of("open a new tab in brave")
        self.assertEqual(a.type, "browser_new_tab")
        self.assertEqual(a.app, "brave")

    # ── Search history via regex ──
    def test_show_search_history_in_chrome(self):
        a = self._action_of("show search history in chrome")
        self.assertEqual(a.type, "browser_show_history")
        self.assertEqual(a.app, "chrome")

    def test_in_brave_show_browser_history(self):
        a = self._action_of("in brave show browser history")
        self.assertEqual(a.type, "browser_show_history")
        self.assertEqual(a.app, "brave")

    # ── Downloads via regex ──
    def test_show_downloads_folder_in_chrome(self):
        a = self._action_of("show downloads folder in chrome")
        self.assertEqual(a.type, "browser_show_downloads")
        self.assertEqual(a.app, "chrome")

    def test_in_brave_show_downloads_folder(self):
        a = self._action_of("in brave show downloads folder")
        self.assertEqual(a.type, "browser_show_downloads")
        self.assertEqual(a.app, "brave")

    # ── Negative: should NOT match as browser-tab command ──
    def test_not_browser_run_code(self):
        p = self.router.plan_for_command("run code")
        # If a plan exists, it must NOT be a browser_switch_tab_number
        if p and p.actions:
            self.assertNotEqual(
                p.actions[0].type, "browser_switch_tab_number",
                msg="'run code' should never be a browser_switch_tab_number"
            )

    def test_not_browser_open_main_py(self):
        # "open main.py" should not be a browser switch tab
        p = self.router.plan_for_command("open main.py")
        if p and p.actions:
            self.assertNotEqual(p.actions[0].type, "browser_switch_tab_number")


# ── 2. BrowserController.get_displayed_browser ───────────────────────────────

class TestGetDisplayedBrowser(unittest.TestCase):
    """
    Tests get_displayed_browser() using mocked win32gui and psutil.
    All tests run without an actual browser open.
    """

    def _make_controller(self):
        from app.browser.controller import BrowserController
        with patch("app.browser.controller.WindowsAppCatalog"):
            return BrowserController()

    @patch("app.browser.controller.HAS_WIN32", True)
    @patch("app.browser.controller.win32gui")
    @patch("app.browser.controller.win32process")
    @patch("app.browser.controller.psutil")
    def test_detects_chrome_in_foreground(self, mock_psutil, mock_win32proc, mock_win32gui):
        mock_win32gui.GetForegroundWindow.return_value = 12345
        mock_win32gui.GetWindowText.return_value = "Hello - Google Chrome"
        mock_win32proc.GetWindowThreadProcessId.return_value = (0, 999)
        mock_psutil.Process.return_value.name.return_value = "chrome.exe"

        ctrl = self._make_controller()
        result = ctrl.get_displayed_browser()

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "chrome")
        self.assertEqual(result["hwnd"], 12345)
        self.assertTrue(result["is_foreground"])

    @patch("app.browser.controller.HAS_WIN32", True)
    @patch("app.browser.controller.win32gui")
    @patch("app.browser.controller.win32process")
    @patch("app.browser.controller.psutil")
    def test_detects_brave_in_foreground(self, mock_psutil, mock_win32proc, mock_win32gui):
        mock_win32gui.GetForegroundWindow.return_value = 54321
        mock_win32gui.GetWindowText.return_value = "GitHub - Brave"
        mock_win32proc.GetWindowThreadProcessId.return_value = (0, 888)
        mock_psutil.Process.return_value.name.return_value = "brave.exe"

        ctrl = self._make_controller()
        result = ctrl.get_displayed_browser()

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "brave")
        self.assertEqual(result["hwnd"], 54321)
        self.assertTrue(result["is_foreground"])

    @patch("app.browser.controller.HAS_WIN32", True)
    @patch("app.browser.controller.win32gui")
    @patch("app.browser.controller.win32process")
    @patch("app.browser.controller.psutil")
    def test_returns_none_when_vscode_in_foreground(self, mock_psutil, mock_win32proc, mock_win32gui):
        mock_win32gui.GetForegroundWindow.return_value = 77777
        mock_win32gui.GetWindowText.return_value = "main.py - VS Code"
        mock_win32proc.GetWindowThreadProcessId.return_value = (0, 555)
        mock_psutil.Process.return_value.name.return_value = "code.exe"

        ctrl = self._make_controller()
        with patch("ctypes.windll.user32") as mock_user32:
            # Simulate empty desktop enumeration
            mock_user32.OpenDesktopW.return_value = 0
            mock_user32.EnumWindows.return_value = None
            result = ctrl.get_displayed_browser()
        # Should return None since VS Code is foreground and no browser on desktop
        self.assertIsNone(result)

    @patch("app.browser.controller.HAS_WIN32", True)
    @patch("app.browser.controller.win32gui")
    @patch("app.browser.controller.win32process")
    @patch("app.browser.controller.psutil")
    def test_preferred_browser_filters_chrome(self, mock_psutil, mock_win32proc, mock_win32gui):
        """Asking for chrome explicitly while brave is foreground returns None."""
        mock_win32gui.GetForegroundWindow.return_value = 54321
        mock_win32gui.GetWindowText.return_value = "GitHub - Brave"
        mock_win32proc.GetWindowThreadProcessId.return_value = (0, 888)
        mock_psutil.Process.return_value.name.return_value = "brave.exe"

        ctrl = self._make_controller()
        # Also patch the internal desktop scan so real running processes don't bleed through
        with patch.object(ctrl, "get_displayed_browser", wraps=ctrl.get_displayed_browser) as _spy:
            # Patch the EnumDesktopWindows fallback path to return nothing
            with patch("ctypes.windll") as mock_dll:
                mock_dll.user32.GetForegroundWindow.return_value = 54321
                mock_dll.user32.OpenDesktopW.return_value = 0
                mock_dll.user32.EnumDesktopWindows.return_value = 0
                mock_dll.user32.IsWindow.return_value = 0
                result = ctrl.get_displayed_browser(preferred_browser="chrome")
        # preferred_browser=chrome should not match brave foreground
        self.assertIsNone(result)


# ── 3. BrowserController guarded methods ─────────────────────────────────────

class TestBrowserControllerGuardedMethods(unittest.TestCase):
    """
    Tests that guarded methods (open_new_tab, switch_to_tab_number, etc.)
    return False with a clear message when no browser is displayed.
    """

    def _make_controller(self):
        from app.browser.controller import BrowserController
        with patch("app.browser.controller.WindowsAppCatalog"):
            ctrl = BrowserController()
        return ctrl

    def _mock_no_browser(self, ctrl):
        ctrl.get_displayed_browser = MagicMock(return_value=None)

    def _mock_browser(self, ctrl, name="brave", hwnd=12345):
        ctrl.get_displayed_browser = MagicMock(return_value={
            "name": name, "hwnd": hwnd, "title": f"Test - {name.capitalize()}",
            "pid": 9999, "is_foreground": True
        })
        ctrl.ensure_browser_focused = MagicMock(return_value=True)
        ctrl.count_tabs = MagicMock(return_value=(9, [f"Tab {i}" for i in range(1, 10)]))

    def test_open_new_tab_no_browser(self):
        ctrl = self._make_controller()
        self._mock_no_browser(ctrl)
        ok, msg = ctrl.open_new_tab()
        self.assertFalse(ok)
        self.assertIn("not currently displayed", msg)

    def test_open_new_tab_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.open_new_tab()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "t")
        self.assertIn("Brave", msg)

    def test_switch_tab_no_browser(self):
        ctrl = self._make_controller()
        self._mock_no_browser(ctrl)
        ok, msg = ctrl.switch_to_tab_number(4)
        self.assertFalse(ok)
        self.assertIn("not currently displayed", msg)

    def test_switch_tab_within_range(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.switch_to_tab_number(4)
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "4")

    def test_switch_tab_out_of_range(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        ctrl.count_tabs = MagicMock(return_value=(3, ["Tab 1", "Tab 2", "Tab 3"]))
        ok, msg = ctrl.switch_to_tab_number(5)
        self.assertFalse(ok)
        self.assertIn("only has 3 tab", msg)

    def test_show_history_no_browser(self):
        ctrl = self._make_controller()
        self._mock_no_browser(ctrl)
        ok, msg = ctrl.show_history()
        self.assertFalse(ok)
        self.assertIn("not currently displayed", msg)

    def test_show_history_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.show_history()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "h")

    def test_show_downloads_no_browser(self):
        ctrl = self._make_controller()
        self._mock_no_browser(ctrl)
        ok, msg = ctrl.show_downloads()
        self.assertFalse(ok)
        self.assertEqual(msg, "NOT_DISPLAYED")

    def test_show_downloads_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.show_downloads()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "j")

    def test_close_tab_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.close_tab()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "w")

    def test_next_tab_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.next_tab()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "tab")

    def test_previous_tab_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.previous_tab()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "shift", "tab")

    def test_reopen_tab_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.reopen_tab()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "shift", "t")

    def test_reload_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.reload()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "r")

    def test_bookmark_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.bookmark_page()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "d")

    def test_incognito_with_browser(self):
        ctrl = self._make_controller()
        self._mock_browser(ctrl)
        with patch("pyautogui.hotkey") as mock_hk:
            ok, msg = ctrl.new_incognito_window()
        self.assertTrue(ok)
        mock_hk.assert_called_once_with("ctrl", "shift", "n")


if __name__ == "__main__":
    unittest.main()
