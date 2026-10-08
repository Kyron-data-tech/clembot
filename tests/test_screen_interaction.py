"""
tests/test_screen_interaction.py

Comprehensive test suite for Clembot Screen Reading, Visual Grounding,
and On-Screen Element Interaction.
Validates:
1. UIElement dataclass representation and properties.
2. Cross-platform accessibility element discovery (Windows & macOS).
3. Whole-screen spoken synthesis (Gemini Vision multimodal & local accessibility fallback).
4. Element grounding: exact, substring, fuzzy, and conversational ordinal indexing ("first one", "second").
5. AI vision coordinate bounding-box grounding.
6. On-screen actions: click, double-click, right-click, select, and open displayed item.
7. FastCommandRouter integration and under-15-word voice responses.
8. ActionRouter execution dispatch.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.vision.screen_interaction import (
    ScreenInteractionService,
    UIElement,
    screen_interaction,
)
from app.commands.fast_router import FastCommandRouter
from app.commands.router import ActionRouter
from app.core.models import AgentAction, AgentPlan, map_plan_to_faq_schema


class TestUIElementBasics(unittest.TestCase):
    """Verifies UIElement creation and defaults."""

    def test_element_creation(self):
        elem = UIElement(
            name="Submit",
            control_type="button",
            x=500,
            y=300,
            width=80,
            height=30,
            window_title="Settings"
        )
        self.assertEqual(elem.name, "Submit")
        self.assertEqual(elem.control_type, "button")
        self.assertEqual(elem.x, 500)
        self.assertEqual(elem.y, 300)
        self.assertEqual(elem.width, 80)
        self.assertEqual(elem.height, 30)
        self.assertEqual(elem.window_title, "Settings")
        self.assertIsNone(elem.raw_control)


class TestElementDiscovery(unittest.TestCase):
    """Tests cross-platform visible element inspection."""

    def setUp(self):
        self.service = ScreenInteractionService()

    def test_get_windows_elements_mock(self):
        """Simulates Windows UIAutomation control hierarchy traversal."""
        mock_child = MagicMock()
        mock_child.ControlTypeName = "ButtonControl"
        mock_child.Name = "Save File"
        mock_rect = MagicMock()
        mock_rect.left = 100
        mock_rect.right = 200
        mock_rect.top = 100
        mock_rect.bottom = 150
        mock_child.BoundingRectangle = mock_rect
        mock_child.GetChildren.return_value = []

        mock_window = MagicMock()
        mock_window.ControlTypeName = "WindowControl"
        mock_window.Name = "Editor"
        mock_window.BoundingRectangle = mock_rect
        mock_window.GetChildren.return_value = [mock_child]

        mock_auto = MagicMock()
        mock_auto.GetForegroundControl.return_value = mock_window
        mock_auto.GetRootControl.return_value = None

        with patch.dict("sys.modules", {"uiautomation": mock_auto}):
            elements = self.service._get_windows_elements(max_elements=10)
            self.assertGreaterEqual(len(elements), 1)
            self.assertEqual(elements[0].name, "Save File")
            self.assertEqual(elements[0].control_type, "button")
            self.assertEqual(elements[0].x, 150)
            self.assertEqual(elements[0].y, 125)

    def test_get_macos_elements_mock(self):
        """Simulates macOS System Events AppleScript output parsing."""
        fake_stdout = "Notes, Save Note, AXButton, 100, 200, 80, 40"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = fake_stdout

        with patch("subprocess.run", return_value=mock_proc):
            elements = self.service._get_macos_elements(max_elements=10)
            self.assertEqual(len(elements), 1)
            elem = elements[0]
            self.assertEqual(elem.name, "Save Note")
            self.assertEqual(elem.control_type, "button")
            self.assertEqual(elem.x, 140)  # 100 + 80//2
            self.assertEqual(elem.y, 220)  # 200 + 40//2
            self.assertEqual(elem.window_title, "Notes")


class TestScreenReadingAndSynthesis(unittest.TestCase):
    """Tests read_whole_screen and local spoken summaries."""

    def setUp(self):
        self.service = ScreenInteractionService()

    def test_synthesize_local_screen_description(self):
        elements = [
            UIElement(name="OK", control_type="button", x=100, y=100),
            UIElement(name="Cancel", control_type="button", x=200, y=100),
            UIElement(name="report.pdf", control_type="item", x=300, y=100),
        ]
        with patch("app.platform_layer.platform_adapter.get_focused_window",
                   return_value={"app": "Visual Studio Code", "title": "main.py - project"}):
            summary = self.service._synthesize_local_screen_description(elements)
            self.assertIn("Visual Studio Code", summary)
            self.assertIn("report.pdf", summary)
            self.assertIn("Tell me what you would like to select or open", summary)

    def test_read_whole_screen_with_ai(self):
        with patch("app.config.settings.settings.gemini_api_key", "test_key"), \
             patch("app.windows.screen_reader.ScreenReader.describe_with_ai",
                   return_value="On your screen, VS Code is open with main.py, and a terminal is running."):
            summary, elements = self.service.read_whole_screen()
            self.assertEqual(summary, "On your screen, VS Code is open with main.py, and a terminal is running.")


class TestElementLocatingAndGrounding(unittest.TestCase):
    """Tests element matching via exact name, fuzzy search, and ordinals."""

    def setUp(self):
        self.service = ScreenInteractionService()
        self.service.last_elements = [
            UIElement(name="Submit Form", control_type="button", x=100, y=200),
            UIElement(name="Cancel", control_type="button", x=300, y=200),
            UIElement(name="Document.docx", control_type="item", x=500, y=200),
            UIElement(name="Accept Terms", control_type="checkbox", x=100, y=400),
        ]
        self.service.last_capture_time = 9999999999.0  # prevent stale re-fetching

    def test_exact_and_substring_match(self):
        elem = self.service.locate_element("Submit Form")
        self.assertIsNotNone(elem)
        self.assertEqual(elem.name, "Submit Form")

        elem2 = self.service.locate_element("button cancel")
        self.assertIsNotNone(elem2)
        self.assertEqual(elem2.name, "Cancel")

    def test_ordinal_grounding(self):
        """User refers to elements read on screen: 'first one', 'second', 'last'."""
        first = self.service.locate_element("first one")
        self.assertIsNotNone(first)
        self.assertEqual(first.name, "Submit Form")

        second = self.service.locate_element("second item")
        self.assertIsNotNone(second)
        self.assertEqual(second.name, "Cancel")

        third = self.service.locate_element("third file")
        self.assertIsNotNone(third)
        self.assertEqual(third.name, "Document.docx")

        last = self.service.locate_element("last button")
        self.assertIsNotNone(last)
        self.assertEqual(last.name, "Accept Terms")

    def test_fuzzy_match(self):
        elem = self.service.locate_element("submt form")
        self.assertIsNotNone(elem)
        self.assertEqual(elem.name, "Submit Form")

    def test_ai_vision_grounding_fallback(self):
        """Simulates Gemini Vision returning bounding box when element not in tree."""
        mock_raw = MagicMock()
        mock_raw.size = (1920, 1080)
        fake_response = MagicMock()
        fake_response.text = '{"found": true, "box_2d": [100, 200, 300, 400], "label": "Download"}'

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response

        with patch("app.config.settings.settings.gemini_api_key", "test_key"), \
             patch("app.windows.screen_reader.ScreenReader.capture_raw", return_value=mock_raw), \
             patch("app.windows.screen_reader.ScreenReader.compress", return_value=(b"fake", 1920, 1080, 1.0)), \
             patch("app.windows.screen_reader.ScreenReader._get_gemini_client", return_value=mock_client):
            elem = self.service._locate_via_ai_vision("Download")
            self.assertIsNotNone(elem)
            self.assertEqual(elem.name, "Download")
            self.assertGreater(elem.x, 0)
            self.assertGreater(elem.y, 0)


class TestOnScreenActions(unittest.TestCase):
    """Tests click, double click, right click, select, and open actions."""

    def setUp(self):
        self.service = ScreenInteractionService()
        self.dummy_elem = UIElement(name="ClickMe", control_type="button", x=250, y=350)
        self.service.last_elements = [self.dummy_elem]
        self.service.last_capture_time = 9999999999.0

    @patch("pyautogui.click")
    @patch("pyautogui.moveTo")
    def test_click_element_single(self, mock_move, mock_click):
        ok, msg = self.service.click_element("ClickMe", click_type="single")
        self.assertTrue(ok)
        self.assertIn("Clicked", msg)
        mock_move.assert_called_with(250, 350, duration=0.15)
        mock_click.assert_called_with(250, 350)

    @patch("pyautogui.doubleClick")
    @patch("pyautogui.moveTo")
    def test_click_element_double(self, mock_move, mock_double):
        ok, msg = self.service.click_element("ClickMe", click_type="double")
        self.assertTrue(ok)
        self.assertIn("Double-clicked", msg)
        mock_double.assert_called_with(250, 350)

    @patch("pyautogui.rightClick")
    @patch("pyautogui.moveTo")
    def test_click_element_right(self, mock_move, mock_right):
        ok, msg = self.service.click_element("ClickMe", click_type="right")
        self.assertTrue(ok)
        self.assertIn("Right-clicked", msg)
        mock_right.assert_called_with(250, 350)

    @patch("pyautogui.click")
    def test_select_element(self, mock_click):
        ok, msg = self.service.select_element("ClickMe")
        self.assertTrue(ok)
        self.assertIn("Selected", msg)
        mock_click.assert_called_with(250, 350)

    @patch("pyautogui.doubleClick")
    @patch("pyautogui.moveTo")
    def test_open_displayed_item_on_screen(self, mock_move, mock_double):
        ok, msg = self.service.open_displayed_item("ClickMe")
        self.assertTrue(ok)
        mock_double.assert_called_with(250, 350)

    def test_click_nonexistent_element(self):
        with patch.object(self.service, "get_visible_elements", return_value=[]):
            self.service.last_elements = []
            ok, msg = self.service.click_element("GhostButton")
            self.assertFalse(ok)
            self.assertIn("couldn't locate", msg)


class TestFastRouterScreenCommands(unittest.TestCase):
    """Tests FastCommandRouter matching for screen reading and interaction voice commands."""

    def setUp(self):
        self.router = FastCommandRouter()

    def _assert_command(self, cmd: str, expected_type: str, expected_text: str = None):
        plan = self.router.plan_for_command(cmd)
        self.assertIsNotNone(plan, f"Failed to route command: {cmd}")
        self.assertGreater(len(plan.actions), 0)
        self.assertEqual(plan.actions[0].type, expected_type)
        if expected_text is not None:
            self.assertEqual(plan.actions[0].text, expected_text)
        words = plan.reply.split()
        self.assertLessEqual(len(words), 15, f"Reply for '{cmd}' exceeds 15 words: '{plan.reply}'")

    def test_screen_read_whole(self):
        self._assert_command("read whole screen", "screen_read_all")
        self._assert_command("read the whole screen", "screen_read_all")
        self._assert_command("read entire screen", "screen_read_all")
        self._assert_command("read my whole screen", "screen_read_all")

    def test_click_element_voice(self):
        self._assert_command("click Submit", "screen_click", "submit")
        self._assert_command("click on Submit", "screen_click", "submit")
        self._assert_command("click the Submit button", "screen_click", "the submit button")
        self._assert_command("click the first one", "screen_click", "the first one")

    def test_double_click_voice(self):
        self._assert_command("double click report.pdf", "screen_double_click", "report.pdf")
        self._assert_command("double click on report.pdf", "screen_double_click", "report.pdf")
        self._assert_command("double click the folder", "screen_double_click", "the folder")

    def test_right_click_voice(self):
        self._assert_command("right click the icon", "screen_right_click", "the icon")
        self._assert_command("right click on report.pdf", "screen_right_click", "report.pdf")

    def test_select_voice(self):
        self._assert_command("select the checkbox on screen", "screen_select", "the checkbox")
        self._assert_command("select Submit on screen", "screen_select", "submit")

    def test_open_displayed_voice(self):
        self._assert_command("open report.pdf on screen", "screen_open", "report.pdf")
        self._assert_command("open that file on screen", "screen_open", "that file")


class TestActionRouterExecution(unittest.TestCase):
    """Verifies that ActionRouter properly dispatches screen actions."""

    def setUp(self):
        self.router = ActionRouter()

    def test_route_screen_read_all(self):
        action = AgentAction(type="screen_read_all", id="test-1")
        with patch("app.vision.screen_interaction.screen_interaction.read_whole_screen",
                   return_value=("Screen summary", [])):
            result = self.router.execute(action)
            self.assertTrue(result.success)
            self.assertEqual(result.message, "Screen summary")

    def test_route_screen_click(self):
        action = AgentAction(type="screen_click", text="Submit", id="test-2")
        with patch("app.vision.screen_interaction.screen_interaction.click_element",
                   return_value=(True, "Clicked on 'Submit'.")):
            result = self.router.execute(action)
            self.assertTrue(result.success)
            self.assertEqual(result.message, "Clicked on 'Submit'.")

    def test_route_screen_select(self):
        action = AgentAction(type="screen_select", text="Option A", id="test-3")
        with patch("app.vision.screen_interaction.screen_interaction.select_element",
                   return_value=(True, "Selected 'Option A'.")):
            result = self.router.execute(action)
            self.assertTrue(result.success)
            self.assertEqual(result.message, "Selected 'Option A'.")

    def test_route_screen_open(self):
        action = AgentAction(type="screen_open", text="report.pdf", id="test-4")
        with patch("app.vision.screen_interaction.screen_interaction.open_displayed_item",
                   return_value=(True, "Opening 'report.pdf'.")):
            result = self.router.execute(action)
            self.assertTrue(result.success)
            self.assertEqual(result.message, "Opening 'report.pdf'.")


if __name__ == "__main__":
    unittest.main()
