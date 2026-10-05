"""
tests/test_platform_macos.py

Unit tests for the macOS platform layer using mocks.
All AppleScript calls, subprocess invocations, and filesystem accesses are mocked
so these tests run correctly on Windows (CI) and macOS alike.

Coverage:
  - applescript.run_applescript / run_multiline_applescript  (8 tests)
  - MacOSAppCatalog                                           (10 tests)
  - MacOSBrowserController                                    (14 tests)
  - MacOSWindowManager                                        (10 tests)
  - MacOSSystemControls                                       (10 tests)
  - MacOSTTSEngine                                            (9 tests)
  - MacOSPermissions                                          (8 tests)
  - MacOSPlatformAdapter                                      (6 tests)

IMPORTANT: patch targets must always be the *usage* site, not the definition site.
  - window_mgr uses: app.platform_layer.macos.window_mgr.run_multiline_applescript
  - system uses:     app.platform_layer.macos.system.run_multiline_applescript
                     app.platform_layer.macos.system.run_applescript
  - browser uses:    app.platform_layer.macos.browser.run_applescript
                     app.platform_layer.macos.browser.run_multiline_applescript
  - apps uses:       app.platform_layer.macos.apps.run_applescript
  - permissions uses:app.platform_layer.macos.permissions.run_applescript
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, call


# ===========================================================================
# 1.  applescript module
# ===========================================================================

class TestRunAppleScript(unittest.TestCase):
    """Tests for app.platform_layer.macos.applescript helpers."""

    def _import(self):
        from app.platform_layer.macos import applescript
        return applescript

    @patch("subprocess.run")
    def test_run_applescript_success(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="hello\n", stderr="")
        mod = self._import()
        ok, out = mod.run_applescript('return "hello"')
        self.assertTrue(ok)
        self.assertEqual(out, "hello")
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_run_applescript_failure(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="script error")
        mod = self._import()
        ok, out = mod.run_applescript("bad script")
        self.assertFalse(ok)
        self.assertIn("script error", out)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5.0))
    def test_run_applescript_timeout(self, mock_run):
        mod = self._import()
        ok, out = mod.run_applescript("slow script")
        self.assertFalse(ok)
        self.assertIn("timed out", out)

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_run_applescript_not_found(self, mock_run):
        mod = self._import()
        ok, out = mod.run_applescript("any script")
        self.assertFalse(ok)
        self.assertIn("not found", out.lower())

    @patch("subprocess.run")
    def test_run_multiline_applescript_success(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="Tab1|||Tab2|||", stderr="")
        mod = self._import()
        ok, out = mod.run_multiline_applescript("tell application ... end tell")
        self.assertTrue(ok)
        self.assertIn("Tab1", out)

    @patch("subprocess.run")
    def test_run_multiline_applescript_error(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="-1743")
        mod = self._import()
        ok, out = mod.run_multiline_applescript("some multiline")
        self.assertFalse(ok)
        self.assertIn("-1743", out)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=8.0))
    def test_run_multiline_applescript_timeout(self, mock_run):
        mod = self._import()
        ok, out = mod.run_multiline_applescript("slow")
        self.assertFalse(ok)
        self.assertIn("timed out", out)

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_run_multiline_applescript_not_found(self, mock_run):
        mod = self._import()
        ok, out = mod.run_multiline_applescript("any")
        self.assertFalse(ok)
        self.assertIn("not found", out.lower())


# ===========================================================================
# 2.  MacOSAppCatalog
# ===========================================================================

class TestMacOSAppCatalog(unittest.TestCase):

    def _make_catalog(self, cached=None):
        """Construct a MacOSAppCatalog with _scan_standard_directories mocked out."""
        from app.platform_layer.macos.apps import MacOSAppCatalog
        with patch.object(MacOSAppCatalog, "_scan_standard_directories", return_value=None):
            cat = MacOSAppCatalog()
        if cached:
            cat._cached_apps = cached
        return cat

    # -- find_app_bundle: builtin catalog hit -----------------------------------

    def test_find_app_bundle_builtin_alias_chrome(self):
        """'chrome' alias resolves to 'Google Chrome' from the built-in catalog."""
        cat = self._make_catalog()
        # No cached apps; the code falls through to returning a synthetic path
        result = cat.find_app_bundle("chrome")
        self.assertIsNotNone(result)
        canonical, path = result
        self.assertEqual(canonical, "Google Chrome")

    def test_find_app_bundle_builtin_alias_vscode(self):
        cat = self._make_catalog()
        result = cat.find_app_bundle("vs code")
        self.assertIsNotNone(result)
        canonical, _ = result
        self.assertEqual(canonical, "Visual Studio Code")

    def test_find_app_bundle_direct_cache_hit(self):
        """Exact normalized name found in scanned app cache."""
        fake_path = Path("/Applications/MyApp.app")
        cat = self._make_catalog(cached={"myapp": fake_path})
        result = cat.find_app_bundle("MyApp")
        self.assertIsNotNone(result)
        canonical, path = result
        self.assertEqual(canonical, "MyApp")
        self.assertEqual(path, fake_path)

    @patch("subprocess.run")
    def test_find_app_bundle_mdfind_fallback(self, mock_run):
        """When not in cache, mdfind returns a hit."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="/Applications/UnknownApp.app\n",
            stderr="",
        )
        cat = self._make_catalog()
        result = cat.find_app_bundle("UnknownApp")
        self.assertIsNotNone(result)
        canonical, path = result
        self.assertEqual(canonical, "UnknownApp")
        self.assertTrue(str(path).endswith("UnknownApp.app"))

    @patch("subprocess.run")
    def test_find_app_bundle_fuzzy_match(self, mock_run):
        """When mdfind finds nothing, fuzzy match on _cached_apps should work."""
        # mdfind returns nothing
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        fake_path = Path("/Applications/Spotify.app")
        cat = self._make_catalog(cached={"spotify": fake_path})
        result = cat.find_app_bundle("spotffy")   # deliberate typo, score ~85
        self.assertIsNotNone(result)
        canonical, path = result
        self.assertEqual(path, fake_path)

    @patch("subprocess.run")
    def test_find_app_bundle_no_match_returns_none(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        cat = self._make_catalog(cached={})
        result = cat.find_app_bundle("xyzqrst_nonexistent_app_12345")
        self.assertIsNone(result)

    # -- is_app_running --------------------------------------------------------

    @patch("app.platform_layer.macos.apps.run_applescript", return_value=(True, "true"))
    def test_is_app_running_true_via_applescript(self, mock_as):
        cat = self._make_catalog()
        self.assertTrue(cat.is_app_running("Finder"))

    @patch("psutil.process_iter")
    @patch("app.platform_layer.macos.apps.run_applescript", return_value=(True, "false"))
    def test_is_app_running_false_when_not_running(self, mock_as, mock_iter):
        mock_iter.return_value = []
        cat = self._make_catalog()
        self.assertFalse(cat.is_app_running("SomeUnknownApp"))

    # -- open_or_activate ------------------------------------------------------

    @patch("subprocess.run")
    def test_open_or_activate_success(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        cat = self._make_catalog()
        msg = cat.open_or_activate("Calculator")
        self.assertIn("Calculator", msg)
        self.assertIn("Opening", msg)

    @patch("subprocess.run")
    def test_open_or_activate_failure_raises(self, mock_run):
        # First call: find via mdfind (return empty). Second call: open (fail)
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),  # mdfind
            Mock(returncode=1, stdout="", stderr="app not found"),  # open -a
        ]
        cat = self._make_catalog()
        with self.assertRaises(RuntimeError):
            cat.open_or_activate("GhostApp999")


# ===========================================================================
# 3.  MacOSBrowserController
# ===========================================================================

class TestMacOSBrowserController(unittest.TestCase):

    def _make_browser(self):
        from app.platform_layer.macos.browser import MacOSBrowserController
        return MacOSBrowserController()

    # -- _resolve_app_name -----------------------------------------------------

    def test_resolve_explicit_chrome(self):
        b = self._make_browser()
        name = b._resolve_app_name("chrome")
        self.assertEqual(name, "Google Chrome")

    def test_resolve_explicit_brave(self):
        b = self._make_browser()
        name = b._resolve_app_name("brave")
        self.assertEqual(name, "Brave Browser")

    @patch("app.platform_layer.macos.browser.run_applescript",
           side_effect=[(True, "true"), (True, "true")])
    def test_resolve_auto_detects_chrome_running(self, mock_as):
        b = self._make_browser()
        name = b._resolve_app_name()
        self.assertEqual(name, "Google Chrome")

    @patch("app.platform_layer.macos.browser.run_applescript",
           side_effect=[(True, "false"), (True, "true"), (True, "true")])
    def test_resolve_auto_detects_brave_if_chrome_not_running(self, mock_as):
        b = self._make_browser()
        name = b._resolve_app_name()
        self.assertEqual(name, "Brave Browser")

    @patch("app.platform_layer.macos.browser.run_applescript",
           side_effect=[(True, "false"), (True, "false")])
    def test_resolve_returns_none_when_no_browser(self, mock_as):
        b = self._make_browser()
        name = b._resolve_app_name()
        self.assertIsNone(name)

    # -- count_and_list_browser_tabs -------------------------------------------

    @patch("app.platform_layer.macos.browser.run_multiline_applescript",
           return_value=(True, "GitHub|||YouTube|||Stack Overflow|||"))
    def test_count_and_list_tabs_success(self, mock_ml):
        b = self._make_browser()
        count, titles = b.count_and_list_browser_tabs({"app_name": "Google Chrome"})
        self.assertEqual(count, 3)
        self.assertEqual(titles[0], "GitHub")
        self.assertEqual(titles[2], "Stack Overflow")

    @patch("app.platform_layer.macos.browser.run_multiline_applescript",
           return_value=(False, "not running"))
    def test_count_and_list_tabs_browser_not_running(self, mock_ml):
        b = self._make_browser()
        count, titles = b.count_and_list_browser_tabs({"app_name": "Google Chrome"})
        self.assertEqual(count, 0)
        self.assertEqual(titles, [])

    # -- switch_browser_tab ----------------------------------------------------

    @patch("app.platform_layer.macos.browser.run_multiline_applescript")
    @patch("app.platform_layer.macos.browser.run_applescript")
    def test_switch_tab_success(self, mock_as, mock_ml):
        # _resolve_app_name("chrome") is called with explicit browser arg in switch_browser_tab
        # Actually switch_browser_tab calls _resolve_app_name() with preferred_browser=None,
        # then count_and_list which calls run_multiline_applescript, then another for the switch
        mock_as.side_effect = [(True, "true"), (True, "true")]  # for auto-detect
        mock_ml.side_effect = [
            (True, "A|||B|||C|||"),   # count_and_list
            (True, ""),               # switch AppleScript
        ]
        b = self._make_browser()
        ok, msg = b.switch_browser_tab(2)
        self.assertTrue(ok)
        self.assertIn("2", msg)

    @patch("app.platform_layer.macos.browser.run_applescript",
           side_effect=[(True, "false"), (True, "false")])
    def test_switch_tab_no_browser(self, mock_as):
        b = self._make_browser()
        ok, msg = b.switch_browser_tab(1)
        self.assertFalse(ok)
        self.assertIn("not currently running", msg.lower())

    # -- open_url / search_web / open_web_destination -------------------------

    @patch("subprocess.Popen")
    def test_open_url_with_explicit_browser(self, mock_popen):
        """With browser='chrome', no AppleScript needed — uses open -a directly."""
        b = self._make_browser()
        msg = b.open_url("https://example.com", browser="chrome")
        self.assertIn("example.com", msg)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertIn("Google Chrome", args)

    @patch("subprocess.Popen")
    def test_search_web_builds_correct_url(self, mock_popen):
        b = self._make_browser()
        msg = b.search_web("clembot tutorial", engine="youtube", browser="chrome")
        self.assertIn("youtube", msg.lower())
        url_arg = mock_popen.call_args[0][0]
        # url is the last arg in ["/usr/bin/open", "-a", "Google Chrome", url]
        self.assertIn("youtube.com", url_arg[3])
        self.assertIn("clembot", url_arg[3])

    @patch("subprocess.Popen")
    def test_open_web_destination_known_site(self, mock_popen):
        b = self._make_browser()
        msg = b.open_web_destination("github", browser="chrome")
        self.assertIsNotNone(msg)
        self.assertIn("github", msg.lower())

    def test_open_web_destination_unknown_returns_none(self):
        b = self._make_browser()
        result = b.open_web_destination("this_site_does_not_exist_xyz")
        self.assertIsNone(result)

    # -- new / close / next / prev tab ----------------------------------------

    @patch("app.platform_layer.macos.browser.run_multiline_applescript",
           return_value=(True, ""))
    def test_new_tab_success(self, mock_ml):
        b = self._make_browser()
        ok, msg = b.new_browser_tab(preferred_browser="chrome")
        self.assertTrue(ok)
        self.assertIn("new tab", msg.lower())

    @patch("app.platform_layer.macos.browser.run_multiline_applescript",
           return_value=(True, ""))
    def test_close_tab_success(self, mock_ml):
        b = self._make_browser()
        ok, msg = b.close_browser_tab(preferred_browser="brave")
        self.assertTrue(ok)
        self.assertIn("closed", msg.lower())


# ===========================================================================
# 4.  MacOSWindowManager
# ===========================================================================

class TestMacOSWindowManager(unittest.TestCase):

    def _make_wm(self):
        from app.platform_layer.macos.window_mgr import MacOSWindowManager
        return MacOSWindowManager()

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, "Xcode|||My Project"))
    def test_get_focused_window_success(self, mock_ml):
        wm = self._make_wm()
        info = wm.get_focused_window()
        self.assertEqual(info["app"], "Xcode")
        self.assertEqual(info["title"], "My Project")

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(False, ""))
    def test_get_focused_window_failure_returns_empty(self, mock_ml):
        wm = self._make_wm()
        info = wm.get_focused_window()
        self.assertEqual(info["app"], "")
        self.assertEqual(info["title"], "")

    @patch("app.platform_layer.macos.window_mgr.run_applescript",
           return_value=(True, ""))
    def test_focus_window_success(self, mock_as):
        wm = self._make_wm()
        ok = wm.focus_window("Finder")
        self.assertTrue(ok)

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, "Finder"))
    def test_minimize_current_success(self, mock_ml):
        wm = self._make_wm()
        msg = wm.minimize_current()
        self.assertIn("Minimized", msg)
        self.assertIn("Finder", msg)

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(False, ""))
    def test_minimize_current_failure_message(self, mock_ml):
        wm = self._make_wm()
        msg = wm.minimize_current()
        self.assertIn("No active window", msg)

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, "Safari"))
    def test_maximize_current_success(self, mock_ml):
        wm = self._make_wm()
        msg = wm.maximize_current()
        self.assertIn("Maximized", msg)

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, "OK"))
    def test_snap_left_success(self, mock_ml):
        wm = self._make_wm()
        msg = wm.snap_left()
        self.assertIn("left half", msg.lower())

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, "OK"))
    def test_snap_right_success(self, mock_ml):
        wm = self._make_wm()
        msg = wm.snap_right()
        self.assertIn("right half", msg.lower())

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, ""))    # no "OK" in output → failure branch
    def test_snap_left_failure_message(self, mock_ml):
        wm = self._make_wm()
        msg = wm.snap_left()
        self.assertIn("Could not snap", msg)

    @patch("app.platform_layer.macos.window_mgr.run_multiline_applescript",
           return_value=(True, ""))
    def test_show_desktop_always_returns_message(self, mock_ml):
        wm = self._make_wm()
        msg = wm.show_desktop()
        self.assertIn("desktop", msg.lower())


# ===========================================================================
# 5.  MacOSSystemControls
# ===========================================================================

class TestMacOSSystemControls(unittest.TestCase):

    def _cls(self):
        from app.platform_layer.macos.system import MacOSSystemControls
        return MacOSSystemControls

    @patch("app.platform_layer.macos.system.run_multiline_applescript",
           return_value=(True, "65"))
    def test_volume_up_returns_percentage(self, mock_ml):
        cls = self._cls()
        msg = cls.volume_up(steps=5)
        self.assertIn("65%", msg)

    @patch("app.platform_layer.macos.system.run_multiline_applescript",
           return_value=(False, "error"))
    def test_volume_up_fallback_message(self, mock_ml):
        cls = self._cls()
        msg = cls.volume_up()
        self.assertIn("increased", msg.lower())

    @patch("app.platform_layer.macos.system.run_multiline_applescript",
           return_value=(True, "20"))
    def test_volume_down_returns_percentage(self, mock_ml):
        cls = self._cls()
        msg = cls.volume_down(steps=5)
        self.assertIn("20%", msg)

    @patch("app.platform_layer.macos.system.run_multiline_applescript",
           return_value=(True, "true"))
    def test_volume_mute_returns_muted(self, mock_ml):
        cls = self._cls()
        msg = cls.volume_mute_toggle()
        self.assertIn("muted", msg.lower())

    @patch("app.platform_layer.macos.system.run_multiline_applescript",
           return_value=(True, "false"))
    def test_volume_mute_returns_unmuted(self, mock_ml):
        cls = self._cls()
        msg = cls.volume_mute_toggle()
        self.assertIn("unmuted", msg.lower())

    @patch("subprocess.Popen")
    def test_copy_text_uses_pbcopy(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc
        cls = self._cls()
        msg = cls.copy_text("hello world")
        self.assertIn("clipboard", msg.lower())
        args = mock_popen.call_args[0][0]
        # args is a list like ['/usr/bin/pbcopy']
        self.assertTrue(any("pbcopy" in a for a in args))

    @patch("subprocess.run")
    def test_get_text_uses_pbpaste(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="clipboard content", stderr="")
        cls = self._cls()
        text = cls.get_text()
        self.assertEqual(text, "clipboard content")

    @patch("subprocess.Popen")
    def test_clear_clipboard(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc
        cls = self._cls()
        msg = cls.clear()
        self.assertIn("cleared", msg.lower())

    @patch("subprocess.run")
    def test_capture_screenshot_creates_file(self, mock_run):
        """screencapture succeeds and the path is returned."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        cls = self._cls()
        fake_dir = Path("/tmp/test_screenshots")
        with (
            patch.object(Path, "mkdir", return_value=None),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "stat") as mock_stat,
        ):
            mock_stat.return_value = Mock(st_size=50 * 1024)  # 50 KB, no compression needed
            # Patch Image.open so it doesn't try to open a real file
            with patch("app.platform_layer.macos.system.Image.open") as mock_img_open:
                out_path, msg = cls.capture_screenshot(fake_dir)
        self.assertIsInstance(out_path, Path)
        self.assertIn("Screenshot", out_path.name)

    @patch("app.platform_layer.macos.system.run_applescript", return_value=(True, ""))
    def test_send_hotkey_applescript_fallback(self, mock_as):
        """Without pyautogui, falls back to AppleScript keystroke."""
        import app.platform_layer.macos.system as sys_mod
        original_pyautogui = sys_mod.pyautogui
        sys_mod.pyautogui = None  # simulate missing pyautogui
        try:
            cls = self._cls()
            cls.send_hotkey("ctrl", "c")
            # The AppleScript fallback should have been called with a keystroke command
            mock_as.assert_called_once()
            call_arg = mock_as.call_args[0][0]
            self.assertIn("keystroke", call_arg)
        finally:
            sys_mod.pyautogui = original_pyautogui


# ===========================================================================
# 6.  MacOSTTSEngine
# ===========================================================================

class TestMacOSTTSEngine(unittest.TestCase):

    def _make_engine(self):
        from app.platform_layer.macos.tts import MacOSTTSEngine
        return MacOSTTSEngine()

    @patch("subprocess.Popen")
    def test_speak_calls_say(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        engine = self._make_engine()
        engine.speak("Hello world")
        args = mock_popen.call_args[0][0]
        self.assertIn("/usr/bin/say", args)
        self.assertIn("Hello world", args)

    @patch("subprocess.Popen")
    def test_speak_skips_empty_string(self, mock_popen):
        engine = self._make_engine()
        engine.speak("")
        mock_popen.assert_not_called()

    @patch("subprocess.Popen")
    def test_speak_uses_voice_and_rate(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        engine = self._make_engine()
        engine.set_voice("Alex")
        engine.set_rate(180)
        engine.speak("Test")
        args = mock_popen.call_args[0][0]
        self.assertIn("-v", args)
        self.assertIn("Alex", args)
        self.assertIn("-r", args)
        self.assertIn("180", args)

    def test_stop_terminates_process(self):
        engine = self._make_engine()
        mock_proc = MagicMock()
        engine._current_proc = mock_proc
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0)
            engine.stop()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(engine._current_proc)

    @patch("subprocess.run")
    def test_get_voices_parses_output(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="Samantha           en_US    # A US English voice\nAlex               en_US    # A US English voice\n",
            stderr="",
        )
        engine = self._make_engine()
        voices = engine.get_voices()
        names = [v["name"] for v in voices]
        self.assertIn("Samantha", names)
        self.assertIn("Alex", names)

    @patch("subprocess.run")
    def test_get_voices_fallback_on_error(self, mock_run):
        mock_run.side_effect = Exception("say not found")
        engine = self._make_engine()
        voices = engine.get_voices()
        # Should fall back to default 4 voices
        self.assertGreaterEqual(len(voices), 4)
        names = [v["name"] for v in voices]
        self.assertIn("Samantha", names)

    def test_set_volume_clamps(self):
        engine = self._make_engine()
        engine.set_volume(2.0)
        self.assertEqual(engine._volume, 1.0)
        engine.set_volume(-0.5)
        self.assertEqual(engine._volume, 0.0)

    def test_set_rate(self):
        engine = self._make_engine()
        engine.set_rate(250)
        self.assertEqual(engine._rate, 250)

    def test_set_voice(self):
        engine = self._make_engine()
        engine.set_voice("Victoria")
        self.assertEqual(engine._voice_id, "Victoria")


# ===========================================================================
# 7.  MacOSPermissions
# ===========================================================================

class TestMacOSPermissions(unittest.TestCase):

    def _cls(self):
        from app.platform_layer.macos.permissions import MacOSPermissions
        return MacOSPermissions

    # -- check_microphone -------------------------------------------------------

    def test_check_microphone_ok(self):
        """Succeeds when pyaudio finds at least one device."""
        cls = self._cls()
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 2
        mock_pa_class = MagicMock(return_value=mock_pa)
        with patch.dict("sys.modules", {"pyaudio": MagicMock(PyAudio=mock_pa_class)}):
            ok, msg = cls.check_microphone()
        self.assertTrue(ok)
        self.assertIn("accessible", msg.lower())

    def test_check_microphone_no_devices(self):
        cls = self._cls()
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_pa_class = MagicMock(return_value=mock_pa)
        with patch.dict("sys.modules", {"pyaudio": MagicMock(PyAudio=mock_pa_class)}):
            ok, msg = cls.check_microphone()
        self.assertFalse(ok)

    # -- check_accessibility ----------------------------------------------------

    @patch("app.platform_layer.macos.permissions.run_applescript",
           return_value=(True, "1"))
    def test_check_accessibility_fallback_success(self, mock_as):
        """If ctypes path doesn't exist, falls back to AppleScript."""
        cls = self._cls()
        with patch("os.path.exists", return_value=False):
            ok, msg = cls.check_accessibility()
        self.assertTrue(ok)
        self.assertIn("granted", msg.lower())

    @patch("app.platform_layer.macos.permissions.run_applescript",
           return_value=(False, "not permitted"))
    def test_check_accessibility_denied(self, mock_as):
        """If AppleScript also fails, returns not granted."""
        cls = self._cls()
        with patch("os.path.exists", return_value=False):
            ok, msg = cls.check_accessibility()
        self.assertFalse(ok)

    # -- check_automation -------------------------------------------------------

    @patch("app.platform_layer.macos.permissions.run_applescript",
           return_value=(True, "admin"))
    def test_check_automation_granted(self, mock_as):
        cls = self._cls()
        ok, msg = cls.check_automation()
        self.assertTrue(ok)
        self.assertIn("granted", msg.lower())

    @patch("app.platform_layer.macos.permissions.run_applescript",
           return_value=(False, "-1743 not permitted"))
    def test_check_automation_denied(self, mock_as):
        cls = self._cls()
        ok, msg = cls.check_automation()
        self.assertFalse(ok)
        self.assertIn("-1743", msg)

    # -- check_all / get_permission_guidance ------------------------------------

    def test_check_all_returns_four_entries(self):
        cls = self._cls()
        with (
            patch.object(cls, "check_microphone", return_value=(True, "ok")),
            patch.object(cls, "check_accessibility", return_value=(True, "ok")),
            patch.object(cls, "check_automation", return_value=(True, "ok")),
            patch.object(cls, "check_screen_recording", return_value=(True, "ok")),
        ):
            results = cls.check_all()
        self.assertEqual(len(results), 4)
        for name, granted, msg in results:
            self.assertTrue(granted)

    def test_get_permission_guidance_all_granted(self):
        cls = self._cls()
        with (
            patch.object(cls, "check_microphone", return_value=(True, "ok")),
            patch.object(cls, "check_accessibility", return_value=(True, "ok")),
            patch.object(cls, "check_automation", return_value=(True, "ok")),
            patch.object(cls, "check_screen_recording", return_value=(True, "ok")),
        ):
            msg = cls.get_permission_guidance()
        self.assertIn("successfully granted", msg.lower())

    def test_get_permission_guidance_shows_missing(self):
        cls = self._cls()
        with (
            patch.object(cls, "check_microphone", return_value=(False, "no mic")),
            patch.object(cls, "check_accessibility", return_value=(True, "ok")),
            patch.object(cls, "check_automation", return_value=(True, "ok")),
            patch.object(cls, "check_screen_recording", return_value=(True, "ok")),
        ):
            msg = cls.get_permission_guidance()
        self.assertIn("Microphone", msg)
        self.assertIn("Privacy", msg)


# ===========================================================================
# 8.  MacOSPlatformAdapter
# ===========================================================================

class TestMacOSPlatformAdapter(unittest.TestCase):
    """High-level smoke tests for MacOSPlatformAdapter delegation."""

    def _make_adapter(self):
        from app.platform_layer.macos.apps import MacOSAppCatalog
        with patch.object(MacOSAppCatalog, "_scan_standard_directories", return_value=None):
            from app.platform_layer.macos.adapter import MacOSPlatformAdapter
            return MacOSPlatformAdapter()

    def test_get_platform_name_starts_with_macos(self):
        adapter = self._make_adapter()
        name = adapter.get_platform_name()
        self.assertTrue(
            name.lower().startswith("macos") or name.lower().startswith("mac"),
            f"Unexpected platform name: {name!r}",
        )

    def test_dangerous_pattern_rm_rf_root(self):
        """rm -rf / must appear in the dangerous patterns list."""
        adapter = self._make_adapter()
        patterns = adapter.get_dangerous_shell_patterns()
        # At least one pattern should match 'rm -rf /'
        matched = any(pat.search("rm -rf /") for pat, _ in patterns)
        self.assertTrue(matched, "No pattern matched 'rm -rf /'")

    def test_dangerous_pattern_diskutil(self):
        adapter = self._make_adapter()
        patterns = adapter.get_dangerous_shell_patterns()
        matched = any(pat.search("diskutil eraseDisk APFS 'Disk' /dev/disk2") for pat, _ in patterns)
        self.assertTrue(matched, "No pattern matched 'diskutil eraseDisk'")

    def test_safe_path_not_protected(self):
        """A path inside the user's home folder is not protected."""
        adapter = self._make_adapter()
        ok = adapter.is_protected_system_path(Path.home() / "Documents" / "myfile.txt")
        self.assertFalse(ok)

    def test_protected_system_path(self):
        """The /usr path is a protected system path.

        On Windows CI, Path('/usr/bin/python3').resolve() returns a Windows path,
        so we use a Mock whose resolve() returns a POSIX-compatible string.
        """
        adapter = self._make_adapter()
        fake_path = MagicMock(spec=Path)
        fake_path.resolve.return_value = Path("/usr/bin/python3")
        # is_protected_system_path calls str(path.resolve()).lower()
        # We need str(resolved) to return '/usr/bin/python3'
        resolved_mock = MagicMock()
        resolved_mock.__str__ = MagicMock(return_value="/usr/bin/python3")
        fake_path.resolve.return_value = resolved_mock
        ok = adapter.is_protected_system_path(fake_path)
        self.assertTrue(ok)

    def test_open_application_delegates_to_catalog(self):
        adapter = self._make_adapter()
        with patch.object(adapter._app_catalog, "open_or_activate", return_value="Opening Calculator."):
            ok, msg = adapter.open_application("calculator")
        self.assertTrue(ok)
        self.assertIn("Calculator", msg)

    def test_create_tts_engine_returns_macos_engine(self):
        adapter = self._make_adapter()
        from app.platform_layer.macos.tts import MacOSTTSEngine
        engine = adapter.create_tts_engine()
        self.assertIsInstance(engine, MacOSTTSEngine)


if __name__ == "__main__":
    unittest.main()
