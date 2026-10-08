"""
tests/test_vscode_full_access.py

Comprehensive tests for Clembot's full VS Code access:
1. VSCodeAdapter cursor position helpers and extended editing methods
2. CodeEditParser cursor-relative voice commands (delete this line, duplicate, comment, etc.)
3. FastRouter exact and pattern matches for VS Code controls (save, format, redo, run)
4. Router execution for cursor-relative tokens and adapter delegation
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.commands.fast_router import FastCommandRouter
from app.commands.router import ActionRouter
from app.core.models import AgentAction
from app.editor.code_edit_parser import parse_voice_edit
from app.editor.vscode_adapter import VSCodeAdapter
from app.ipc.server import ipc_server


class TestVSCodeAdapterFullAccess(unittest.TestCase):
    def setUp(self):
        self.adapter = VSCodeAdapter()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_cursor_line_and_column_defaults(self):
        ipc_server.state.cursor_line = 0
        ipc_server.state.cursor_column = 0
        self.assertEqual(self.adapter.get_cursor_line(), 1)
        self.assertEqual(self.adapter.get_cursor_column(), 1)

    def test_cursor_line_and_column_active(self):
        ipc_server.state.cursor_line = 42
        ipc_server.state.cursor_column = 15
        self.assertEqual(self.adapter.get_cursor_line(), 42)
        self.assertEqual(self.adapter.get_cursor_column(), 15)

    def test_delete_lines_disk_fallback(self):
        test_file = self.tmp_path / "sample.py"
        test_file.write_text("line 1\nline 2\nline 3\nline 4\n", encoding="utf-8")

        with patch.object(self.adapter, "is_available", return_value=False), \
             patch.object(self.adapter, "get_active_file", return_value=test_file):
            ok = self.adapter.delete_lines(2, 3)
            self.assertTrue(ok)
            lines = test_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines, ["line 1", "line 4"])

    def test_insert_line_disk_fallback(self):
        test_file = self.tmp_path / "sample.py"
        test_file.write_text("line 1\nline 2\n", encoding="utf-8")

        with patch.object(self.adapter, "is_available", return_value=False), \
             patch.object(self.adapter, "get_active_file", return_value=test_file):
            ok = self.adapter.insert_line(2, "inserted")
            self.assertTrue(ok)
            lines = test_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines, ["line 1", "inserted", "line 2"])

    def test_replace_line_disk_fallback(self):
        test_file = self.tmp_path / "sample.py"
        test_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")

        with patch.object(self.adapter, "is_available", return_value=False), \
             patch.object(self.adapter, "get_active_file", return_value=test_file):
            ok = self.adapter.replace_line(2, "new line 2")
            self.assertTrue(ok)
            lines = test_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines, ["line 1", "new line 2", "line 3"])

    def test_ipc_command_delegation_when_available(self):
        with patch.object(self.adapter, "is_available", return_value=True), \
             patch("app.editor.vscode_adapter._ipc_post", return_value={"success": True}):
            self.assertTrue(self.adapter.format_document())
            self.assertTrue(self.adapter.redo())
            self.assertTrue(self.adapter.duplicate_line(10))
            self.assertTrue(self.adapter.toggle_comment(5))
            self.assertTrue(self.adapter.go_to_definition())
            self.assertTrue(self.adapter.select_line(3))


class TestCodeEditParserCursorRelative(unittest.TestCase):
    def test_delete_this_line(self):
        r = parse_voice_edit("delete this line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "DELETE_LINE:0")
        self.assertEqual(r.line_number, 0)
        self.assertTrue(r.needs_confirmation)

    def test_delete_current_line(self):
        r = parse_voice_edit("delete current line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "DELETE_LINE:0")

    def test_comment_this_line(self):
        r = parse_voice_edit("comment this line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "COMMENT_LINE:0")
        self.assertEqual(r.line_number, 0)

    def test_uncomment_this_line(self):
        r = parse_voice_edit("uncomment this line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "UNCOMMENT_LINE:0")

    def test_duplicate_this_line(self):
        r = parse_voice_edit("duplicate this line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "DUPLICATE_LINE:0")

    def test_duplicate_line_bare(self):
        r = parse_voice_edit("duplicate line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "DUPLICATE_LINE:0")

    def test_select_this_line(self):
        r = parse_voice_edit("select this line")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "SELECT_LINE:0")

    def test_move_line_up_relative(self):
        r = parse_voice_edit("move line up")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "MOVE_LINE_UP:0")

    def test_move_line_down_relative(self):
        r = parse_voice_edit("move line down")
        self.assertIsNotNone(r)
        self.assertEqual(r.token, "MOVE_LINE_DOWN:0")


class TestFastRouterVSCodeControls(unittest.TestCase):
    def setUp(self):
        self.router = FastCommandRouter()

    def test_save_exact_matches(self):
        for cmd in ["save", "save file", "save this file", "save document", "save changes"]:
            plan = self.router.plan_for_command(cmd)
            self.assertIsNotNone(plan, f"Failed for {cmd}")
            self.assertEqual(plan.actions[0].type, "save")

    def test_save_all_exact_matches(self):
        plan = self.router.plan_for_command("save all")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.actions[0].type, "vscode_save_all")

    def test_format_document_exact_matches(self):
        for cmd in ["format document", "format code", "format file", "format the file"]:
            plan = self.router.plan_for_command(cmd)
            self.assertIsNotNone(plan, f"Failed for {cmd}")
            self.assertEqual(plan.actions[0].type, "vscode_format")

    def test_redo_exact_matches(self):
        for cmd in ["redo", "redo edit", "redo change", "redo that"]:
            plan = self.router.plan_for_command(cmd)
            self.assertIsNotNone(plan, f"Failed for {cmd}")
            self.assertEqual(plan.actions[0].type, "redo")

    def test_run_code_exact_matches(self):
        for cmd in ["run code", "run this code", "run the code", "run script"]:
            plan = self.router.plan_for_command(cmd)
            self.assertIsNotNone(plan, f"Failed for {cmd}")
            self.assertEqual(plan.actions[0].type, "vscode_run_code")

    def test_duplicate_line_exact_matches(self):
        plan = self.router.plan_for_command("duplicate this line")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.actions[0].type, "vscode_edit")
        self.assertEqual(plan.actions[0].text, "DUPLICATE_LINE:0")


class TestActionRouterVSCodeExecution(unittest.TestCase):
    def setUp(self):
        self.router = ActionRouter()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_execute_save_uses_vscode_save_when_available(self):
        with patch.object(self.router.vscode, "is_available", return_value=True), \
             patch.object(self.router.vscode, "save", return_value=True) as mock_save:
            act = AgentAction(type="save")
            res = self.router.execute(act)
            self.assertTrue(res.success)
            mock_save.assert_called_once()

    def test_execute_redo_uses_vscode_redo_when_available(self):
        with patch.object(self.router.vscode, "is_available", return_value=True), \
             patch.object(self.router.vscode, "redo", return_value=True) as mock_redo:
            act = AgentAction(type="redo")
            res = self.router.execute(act)
            self.assertTrue(res.success)
            mock_redo.assert_called_once()

    def test_execute_vscode_format_uses_adapter(self):
        with patch.object(self.router.vscode, "format_document", return_value=True) as mock_format:
            act = AgentAction(type="vscode_format")
            res = self.router.execute(act)
            self.assertTrue(res.success)
            mock_format.assert_called_once()

    def test_execute_delete_line_zero_resolves_to_cursor(self):
        test_file = self.tmp_path / "code.py"
        test_file.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")

        with patch.object(self.router.vscode, "get_active_file", return_value=test_file), \
             patch.object(self.router.vscode, "get_cursor_line", return_value=2), \
             patch.object(self.router.vscode, "open_file"):
            act = AgentAction(type="vscode_edit", text="DELETE_LINE:0")
            res = self.router.execute(act)
            self.assertTrue(res.success)
            self.assertIn("Line 2 deleted.", res.message)


if __name__ == "__main__":
    unittest.main()
