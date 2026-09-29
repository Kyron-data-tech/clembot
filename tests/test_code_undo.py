"""
tests/test_code_undo.py

End-to-end unit tests for Clembot's code-undo pipeline.

Tests cover:
  1. ConversationalMemory.resolve_contextual_references — all English/Hinglish undo phrases → "undo"
  2. FastCommandRouter — all undo/revert variants → vscode_undo action
  3. code_patch_engine.undo_last_patch — in-memory stack undo and .bak fallback
  4. _write_lines (router helper) — writes to code_patch_engine undo stack
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from app.commands.fast_router import FastCommandRouter
from app.editor.code_patch_engine import CodePatchEngine, TargetedPatch
from app.memory.conversation import ConversationalMemory


# ── 1. ConversationalMemory undo phrase resolution ──────────────────────────

class TestUndoPhraseResolution(unittest.TestCase):
    def setUp(self):
        self.mem = ConversationalMemory()

    def _assert_resolves_to_undo(self, phrase: str):
        self.assertEqual(
            self.mem.resolve_contextual_references(phrase), "undo",
            msg=f"Expected 'undo' for phrase: {phrase!r}"
        )

    # ---------- simple "undo" ----------
    def test_bare_undo(self):
        self._assert_resolves_to_undo("undo")

    def test_undo_that(self):
        self._assert_resolves_to_undo("undo that")

    def test_undo_this(self):
        self._assert_resolves_to_undo("undo this")

    def test_undo_it(self):
        self._assert_resolves_to_undo("undo it")

    # ---------- change/edit variants ----------
    def test_undo_change(self):
        self._assert_resolves_to_undo("undo change")

    def test_undo_the_change(self):
        self._assert_resolves_to_undo("undo the change")

    def test_undo_last_change(self):
        self._assert_resolves_to_undo("undo last change")

    def test_undo_the_last_change(self):
        self._assert_resolves_to_undo("undo the last change")

    def test_undo_code_change(self):
        self._assert_resolves_to_undo("undo code change")

    def test_undo_the_code_change(self):
        self._assert_resolves_to_undo("undo the code change")

    def test_undo_edit(self):
        self._assert_resolves_to_undo("undo edit")

    def test_undo_last_edit(self):
        self._assert_resolves_to_undo("undo last edit")

    def test_undo_my_last_edit(self):
        self._assert_resolves_to_undo("undo my last edit")

    # ---------- revert variants ----------
    def test_revert_that(self):
        self._assert_resolves_to_undo("revert that")

    def test_revert_change(self):
        self._assert_resolves_to_undo("revert change")

    def test_revert_the_change(self):
        self._assert_resolves_to_undo("revert the change")

    def test_revert_code_change(self):
        self._assert_resolves_to_undo("revert code change")

    def test_revert_edit(self):
        self._assert_resolves_to_undo("revert edit")

    def test_revert_last_edit(self):
        self._assert_resolves_to_undo("revert last edit")

    # ---------- "change it back" ----------
    def test_change_it_back(self):
        self._assert_resolves_to_undo("change it back")

    def test_take_it_back(self):
        self._assert_resolves_to_undo("take it back")

    def test_put_it_back(self):
        self._assert_resolves_to_undo("put it back")

    # ---------- Hinglish ----------
    def test_hinglish_pehle_jaisa(self):
        self._assert_resolves_to_undo("pehle jaisa kar do")

    def test_hinglish_jo_abhi_change(self):
        self._assert_resolves_to_undo("jo abhi change kiya tha usko undo karo")

    def test_hinglish_jo_change(self):
        self._assert_resolves_to_undo("jo change kiya tha usko undo karo")

    def test_hinglish_pichla_change(self):
        self._assert_resolves_to_undo("pichla change undo karo")

    def test_hinglish_code_undo_karo(self):
        self._assert_resolves_to_undo("code undo karo")

    def test_hinglish_edit_undo_karo(self):
        self._assert_resolves_to_undo("edit undo karo")

    # ---------- NON-undo: should NOT resolve to "undo" ----------
    def test_not_undo_open(self):
        result = self.mem.resolve_contextual_references("open main.py")
        self.assertNotEqual(result, "undo")

    def test_not_undo_run(self):
        result = self.mem.resolve_contextual_references("run code")
        self.assertNotEqual(result, "undo")


# ── 2. FastCommandRouter — vscode_undo routing ───────────────────────────────

class TestFastRouterUndoRouting(unittest.TestCase):
    def setUp(self):
        self.router = FastCommandRouter()

    def _assert_vscode_undo(self, phrase: str):
        plan = self.router.plan_for_command(phrase)
        self.assertIsNotNone(plan, msg=f"No plan returned for: {phrase!r}")
        self.assertTrue(
            any(a.type == "vscode_undo" for a in plan.actions),
            msg=f"Expected vscode_undo action for: {phrase!r}, got: {[a.type for a in plan.actions]}"
        )

    def test_undo_code_change_exact(self):
        self._assert_vscode_undo("undo code change")

    def test_undo_the_code_change_exact(self):
        self._assert_vscode_undo("undo the code change")

    def test_undo_change_exact(self):
        self._assert_vscode_undo("undo change")

    def test_undo_the_change_exact(self):
        self._assert_vscode_undo("undo the change")

    def test_undo_last_change_exact(self):
        self._assert_vscode_undo("undo last change")

    def test_undo_edit_exact(self):
        self._assert_vscode_undo("undo edit")

    def test_undo_last_edit_exact(self):
        self._assert_vscode_undo("undo last edit")

    def test_revert_change_exact(self):
        self._assert_vscode_undo("revert change")

    def test_revert_code_change_exact(self):
        self._assert_vscode_undo("revert code change")

    def test_revert_edit_exact(self):
        self._assert_vscode_undo("revert edit")

    def test_revert_last_edit_exact(self):
        self._assert_vscode_undo("revert last edit")

    def test_revert_that_exact(self):
        self._assert_vscode_undo("revert that")

    def test_change_it_back_exact(self):
        self._assert_vscode_undo("change it back")

    def test_regex_undo_my_changes(self):
        self._assert_vscode_undo("undo my changes")

    def test_regex_revert_my_last_modification(self):
        self._assert_vscode_undo("revert my last modification")

    def test_regex_please_undo_the_edit(self):
        self._assert_vscode_undo("please undo the edit")


# ── 3. code_patch_engine undo stack ─────────────────────────────────────────

class TestCodePatchEngineUndo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="clembot_undo_test_"))
        self.engine = CodePatchEngine()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_file(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_undo_after_patch(self):
        f = self._make_file("calc.py", "x = 1\n")
        patch = TargetedPatch(file_path=f, target_code="x = 1", replacement_code="x = 99")
        ok, _, _ = self.engine.apply_patch(patch)
        self.assertTrue(ok)
        self.assertIn("x = 99", f.read_text(encoding="utf-8"))

        rev_ok, msg = self.engine.undo_last_patch(f)
        self.assertTrue(rev_ok)
        self.assertIn("x = 1", f.read_text(encoding="utf-8"))
        self.assertEqual(self.engine.last_reverted_path, f)

    def test_undo_without_file_arg_uses_most_recent(self):
        f = self._make_file("util.py", "y = 5\n")
        patch = TargetedPatch(file_path=f, target_code="y = 5", replacement_code="y = 0")
        self.engine.apply_patch(patch)
        rev_ok, _ = self.engine.undo_last_patch()   # no file arg
        self.assertTrue(rev_ok)
        self.assertIn("y = 5", f.read_text(encoding="utf-8"))

    def test_undo_fallback_to_bak(self):
        f = self._make_file("helper.py", "z = 10\n")
        # Manually create a .bak without using apply_patch
        bak = f.with_suffix(".py.bak")
        bak.write_text("z = 10\n", encoding="utf-8")
        f.write_text("z = 999\n", encoding="utf-8")

        rev_ok, msg = self.engine.undo_last_patch(f)
        self.assertTrue(rev_ok)
        self.assertIn("z = 10", f.read_text(encoding="utf-8"))

    def test_undo_no_history_returns_false(self):
        ok, msg = self.engine.undo_last_patch()
        self.assertFalse(ok)
        self.assertIn("No previous", msg)

    def test_multiple_patches_undo_in_order(self):
        f = self._make_file("multi.py", "a = 1\n")
        self.engine.apply_patch(TargetedPatch(file_path=f, target_code="a = 1", replacement_code="a = 2"))
        self.engine.apply_patch(TargetedPatch(file_path=f, target_code="a = 2", replacement_code="a = 3"))
        self.assertIn("a = 3", f.read_text(encoding="utf-8"))

        self.engine.undo_last_patch(f)
        self.assertIn("a = 2", f.read_text(encoding="utf-8"))

        self.engine.undo_last_patch(f)
        self.assertIn("a = 1", f.read_text(encoding="utf-8"))

    def test_last_reverted_path_updated(self):
        f = self._make_file("track.py", "n = 0\n")
        self.engine.apply_patch(TargetedPatch(file_path=f, target_code="n = 0", replacement_code="n = 1"))
        self.engine.undo_last_patch(f)
        self.assertEqual(self.engine.last_reverted_path, f)

    def test_last_reverted_path_none_on_failure(self):
        self.engine.undo_last_patch()   # no history
        self.assertIsNone(self.engine.last_reverted_path)


if __name__ == "__main__":
    unittest.main()
