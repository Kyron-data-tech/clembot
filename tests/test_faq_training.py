"""
Unit tests for the Clembot FAQ Training Set (Windows + macOS).
Validates:
1. Dataset structure, completeness, and schema conformity.
2. Every spoken reply is strictly under 15 words (strict voice UX requirement).
3. Routing accuracy for Windows and macOS FAQ examples.
4. Correct intent and slot mapping via map_plan_to_faq_schema().
5. Destructive operations require confirmation.
"""

import json
import os
import unittest
from unittest.mock import patch

from app.commands.fast_router import FastCommandRouter
from app.core.models import AgentAction, AgentPlan, FAQIntentSchema, map_plan_to_faq_schema
from app.editor.code_edit_parser import parse_voice_edit


class TestFAQTrainingDatasetIntegrity(unittest.TestCase):
    """Validates the schema and constraints of data/faq_training_set.json."""

    @classmethod
    def setUpClass(cls):
        dataset_path = os.path.join(os.path.dirname(__file__), "..", "data", "faq_training_set.json")
        with open(dataset_path, "r", encoding="utf-8") as f:
            cls.dataset = json.load(f)

    def test_dataset_is_non_empty(self):
        self.assertGreater(len(self.dataset), 50, "Dataset should contain at least 50 training items.")

    def test_all_intents_are_valid(self):
        valid_intents = {
            "open_app", "open_file", "open_folder", "open_url",
            "browser_tab", "browser_page", "vscode_open", "vscode_edit",
            "window_switch", "system"
        }
        for item in self.dataset:
            self.assertIn(
                item["intent"], valid_intents,
                f"Item {item.get('id')} has invalid intent: {item.get('intent')}"
            )

    def test_all_spoken_replies_under_15_words(self):
        """CRITICAL: Spoken replies must be under 15 words for snappy voice UX."""
        for item in self.dataset:
            reply = item.get("reply", "")
            words = reply.strip().split()
            self.assertLessEqual(
                len(words), 15,
                f"Item {item.get('id')} reply exceeds 15 words ({len(words)} words): '{reply}'"
            )

    def test_all_slots_contain_required_keys(self):
        required_slot_keys = {"app", "path", "url", "tab_index", "line", "end_line", "text"}
        for item in self.dataset:
            slots = item.get("slots", {})
            self.assertTrue(
                required_slot_keys.issubset(slots.keys()),
                f"Item {item.get('id')} missing required slot keys. Found: {list(slots.keys())}"
            )

    def test_destructive_operations_flag_confirmation(self):
        """Line deletions, clear data, and force closes must flag needs_confirmation=True."""
        destructive_identifiers = {"A1-19", "A4-22", "A6-02", "A6-03", "B1-16", "B4-22", "B6-02"}
        for item in self.dataset:
            if item.get("id") in destructive_identifiers:
                self.assertTrue(
                    item.get("needs_confirmation", False),
                    f"Item {item.get('id')} ({item.get('section')}) must have needs_confirmation=True"
                )


class TestFAQSchemaMapping(unittest.TestCase):
    """Tests map_plan_to_faq_schema for all 10 intent categories across OSes."""

    def test_open_app_mapping(self):
        plan = AgentPlan(reply="Opening Chrome.", actions=[AgentAction(type="open_app", app="chrome")])
        schema_win = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema_win.intent, "open_app")
        self.assertEqual(schema_win.os, "windows")
        self.assertEqual(schema_win.slots["app"], "chrome")

        schema_mac = map_plan_to_faq_schema(plan, os_name="macos")
        self.assertEqual(schema_mac.intent, "open_app")
        self.assertEqual(schema_mac.os, "macos")

    def test_open_file_mapping(self):
        plan = AgentPlan(reply="Opening resume.pdf.", actions=[AgentAction(type="open_file", path="resume.pdf")])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "open_file")
        self.assertEqual(schema.slots["path"], "resume.pdf")

    def test_open_folder_mapping(self):
        plan = AgentPlan(reply="Opening Downloads.", actions=[AgentAction(type="open_folder", path="Downloads")])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "open_folder")
        self.assertEqual(schema.slots["path"], "Downloads")

    def test_open_url_mapping(self):
        plan = AgentPlan(reply="Opening site.", actions=[AgentAction(type="open_url", url="https://google.com")])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "open_url")
        self.assertEqual(schema.slots["url"], "https://google.com")

    def test_browser_tab_mapping(self):
        plan = AgentPlan(reply="Tab 3.", actions=[AgentAction(type="browser_switch_tab_number", amount=3)])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "browser_tab")
        self.assertEqual(schema.slots["tab_index"], 3)

    def test_browser_page_mapping(self):
        plan = AgentPlan(reply="Opening history.", actions=[AgentAction(type="browser_show_history")])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "browser_page")

    def test_vscode_open_mapping(self):
        plan = AgentPlan(reply="Opening app.js at line 42.", actions=[AgentAction(type="vscode_open_file_at_line", path="app.js", line_number=42)])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "vscode_open")
        self.assertEqual(schema.slots["path"], "app.js")
        self.assertEqual(schema.slots["line"], 42)

    def test_vscode_edit_mapping(self):
        plan = AgentPlan(reply="Line 20 replaced.", actions=[AgentAction(type="vscode_edit", line_number=20, text="x = 5")])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "vscode_edit")
        self.assertEqual(schema.slots["line"], 20)
        self.assertEqual(schema.slots["text"], "x = 5")

    def test_window_switch_mapping(self):
        plan = AgentPlan(reply="Switching window.", actions=[AgentAction(type="switch_window")])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "window_switch")

    def test_system_mapping(self):
        plan = AgentPlan(reply="Cancelled.", actions=[])
        schema = map_plan_to_faq_schema(plan, os_name="windows")
        self.assertEqual(schema.intent, "system")


class TestFAQFastRouterResponses(unittest.TestCase):
    """Tests the FastCommandRouter against typical phrases from the FAQ."""

    def setUp(self):
        self.router = FastCommandRouter()

    def _check_command(self, cmd: str, expected_intent: str, expected_action_type: str = None):
        plan = self.router.plan_for_command(cmd)
        self.assertIsNotNone(plan, f"FastCommandRouter should resolve '{cmd}'")
        words = plan.reply.strip().split()
        self.assertLessEqual(len(words), 15, f"Reply for '{cmd}' exceeds 15 words: '{plan.reply}'")
        schema = map_plan_to_faq_schema(plan)
        self.assertEqual(schema.intent, expected_intent, f"Command '{cmd}' mapped to wrong intent: {schema.intent}")
        if expected_action_type and plan.actions:
            self.assertEqual(plan.actions[0].type, expected_action_type)

    def test_windows_apps(self):
        self._check_command("open chrome", "open_app", "open_app")
        self._check_command("open edge", "open_app", "open_app")
        self._check_command("open vs code", "open_app", "open_app")
        self._check_command("open notepad", "open_app", "open_app")
        self._check_command("open calculator", "open_app", "open_app")
        self._check_command("open powershell", "open_app", "open_app")
        self._check_command("open file explorer", "open_app", "open_app")

    def test_folders(self):
        self._check_command("open downloads", "open_folder", "open_folder")
        self._check_command("show my downloads folder", "open_folder", "open_folder")
        self._check_command("open documents", "open_folder", "open_folder")
        self._check_command("open desktop", "open_folder", "open_folder")
        self._check_command("open recent files", "open_folder", "open_recent_files")
        self._check_command("open recycle bin", "open_folder", "open_folder")

    def test_browser_controls(self):
        self._check_command("new tab", "browser_tab", "browser_new_tab")
        self._check_command("close tab", "browser_tab", "browser_close_tab")
        self._check_command("reopen closed tab", "browser_tab", "browser_reopen_tab")
        self._check_command("next tab", "browser_tab", "browser_next_tab")
        self._check_command("previous tab", "browser_tab", "browser_prev_tab")
        self._check_command("go to tab 3", "browser_tab", "browser_switch_tab_number")
        self._check_command("go to the last tab", "browser_tab", "browser_last_tab")
        self._check_command("open history", "browser_page", "browser_show_history")
        self._check_command("bookmark this page", "browser_page", "browser_bookmark_page")
        self._check_command("refresh", "browser_page", "browser_reload")
        self._check_command("clear browsing data", "browser_page", "browser_clear_data")

    def test_window_switching(self):
        self._check_command("switch window", "window_switch", "switch_window")
        self._check_command("task view", "window_switch", "task_view")
        self._check_command("show desktop", "window_switch", "show_desktop")
        self._check_command("minimize this", "window_switch", "window_minimize")
        self._check_command("maximize this", "window_switch", "window_maximize")

    def test_vscode_open_and_jumps(self):
        self._check_command("open command palette", "vscode_open", "vscode_command_palette")
        self._check_command("toggle sidebar", "vscode_open", "vscode_toggle_sidebar")
        self._check_command("go to line 80", "vscode_open", "vscode_jump_line")
        self._check_command("open app.js at line 42", "vscode_open", "vscode_open_file_at_line")
        self._check_command("go to line 42 and column 10", "vscode_open", "vscode_jump_line")
        self._check_command("format the file", "vscode_edit", "vscode_format")

    def test_code_edits_and_confirmations(self):
        del_plan = self.router.plan_for_command("delete line 15")
        self.assertIsNotNone(del_plan)
        self.assertTrue(del_plan.needs_confirmation)
        self.assertLessEqual(len(del_plan.reply.split()), 15)

        del_range = self.router.plan_for_command("delete lines 10 to 14")
        self.assertIsNotNone(del_range)
        self.assertTrue(del_range.needs_confirmation)
        self.assertLessEqual(len(del_range.reply.split()), 15)

        replace_plan = self.router.plan_for_command("replace line 20 with x = 5")
        self.assertIsNotNone(replace_plan)
        self.assertFalse(replace_plan.needs_confirmation)
        self.assertLessEqual(len(replace_plan.reply.split()), 15)


class TestCodeEditParserFAQCoverage(unittest.TestCase):
    """Validates that code_edit_parser handles all line operations and obeys constraints."""

    def test_delete_requires_confirmation(self):
        parsed = parse_voice_edit("delete line 15")
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.needs_confirmation)
        self.assertIn("deleted", parsed.summary.lower())
        self.assertLessEqual(len(parsed.summary.split()), 15)

    def test_insert_below(self):
        parsed = parse_voice_edit("insert a new line below line 8")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.line_number, 8)
        self.assertLessEqual(len(parsed.summary.split()), 15)

    def test_duplicate_line(self):
        parsed = parse_voice_edit("duplicate line 25")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.line_number, 25)
        self.assertLessEqual(len(parsed.summary.split()), 15)

    def test_comment_and_uncomment(self):
        c_parsed = parse_voice_edit("comment out line 30")
        self.assertIsNotNone(c_parsed)
        self.assertEqual(c_parsed.line_number, 30)
        self.assertLessEqual(len(c_parsed.summary.split()), 15)

        u_parsed = parse_voice_edit("uncomment line 30")
        self.assertIsNotNone(u_parsed)
        self.assertEqual(u_parsed.line_number, 30)
        self.assertLessEqual(len(u_parsed.summary.split()), 15)

    def test_indent_and_outdent(self):
        i_parsed = parse_voice_edit("indent line 12")
        self.assertIsNotNone(i_parsed)
        self.assertEqual(i_parsed.line_number, 12)
        self.assertLessEqual(len(i_parsed.summary.split()), 15)

        o_parsed = parse_voice_edit("outdent line 12")
        self.assertIsNotNone(o_parsed)
        self.assertEqual(o_parsed.line_number, 12)
        self.assertLessEqual(len(o_parsed.summary.split()), 15)


if __name__ == "__main__":
    unittest.main()
