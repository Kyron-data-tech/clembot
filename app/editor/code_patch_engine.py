"""
app/editor/code_patch_engine.py

Targeted Semantic Code Patching & Safety Engine for Clembot.

Key Capabilities:
1. Targeted block-level patching (never whole-file regeneration).
2. Exact matching with whitespace-tolerant and AST-anchored fallbacks.
3. Automated unified diff generation.
4. Pre-modification safety backups (.bak) and in-memory undo stack.
5. Post-modification syntax validation (Python AST, JSON, bracket balancing).
6. Automated rollback if syntax validation fails.
7. Multi-file sequential patch coordination.
"""

import ast
import difflib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.logging.logger import logger


@dataclass
class TargetedPatch:
    file_path: Path
    target_code: str                          # Exact or fuzzy snippet to locate and replace
    replacement_code: str                     # New code to substitute
    explanation: str = ""                     # Spoken / readable explanation
    line_hint: Optional[int] = None           # Optional line number hint
    symbol_name: Optional[str] = None         # Optional function/class/method name
    diff: str = ""                            # Generated unified diff
    action_type: str = "replace"              # "replace", "insert_before", "insert_after", "delete"
    patch_action: Optional[str] = None        # Alias for action_type

    def __post_init__(self):
        if self.patch_action and (not self.action_type or self.action_type == "replace"):
            self.action_type = self.patch_action
        elif not self.patch_action:
            self.patch_action = self.action_type


class CodePatchEngine:
    """
    Executes precise, safe, non-destructive semantic patches on source code files.
    Preserves existing code structure, formatting, and file line endings.
    """

    def __init__(self):
        self._undo_history: List[Dict[str, Any]] = []
        self.last_reverted_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # EOL & File I/O
    # ------------------------------------------------------------------

    @staticmethod
    def read_file_with_eol(path: Path) -> Tuple[str, str]:
        """
        Reads file as raw bytes, decodes as UTF-8 (fallback cp1252),
        and detects dominant EOL style ('\\r\\n' or '\\n').
        """
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")

        crlf_count = text.count("\r\n")
        lf_count = text.count("\n") - crlf_count
        eol = "\r\n" if crlf_count >= lf_count else "\n"
        return text, eol

    @staticmethod
    def write_file_preserving_eol(path: Path, text: str, eol: str) -> None:
        """
        Normalizes internal line endings to the file's native EOL style
        and writes raw bytes to prevent Windows stdio translation doubling.
        """
        # Normalize all newlines to detected EOL
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if eol == "\r\n":
            normalized = normalized.replace("\n", "\r\n")
        path.write_bytes(normalized.encode("utf-8"))

    # ------------------------------------------------------------------
    # Diff Generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_unified_diff(original: str, modified: str, filename: str = "file") -> str:
        """Generates a standard unified diff between original and modified text."""
        orig_lines = original.splitlines(keepends=True)
        mod_lines = modified.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines,
            mod_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm=""
        )
        return "".join(diff)

    # ------------------------------------------------------------------
    # Target Block Locating (Exact -> Whitespace-Tolerant -> Line Range)
    # ------------------------------------------------------------------

    @classmethod
    def locate_target_block(
        cls,
        full_content: str,
        target_code: str,
        line_hint: Optional[int] = None
    ) -> Optional[Tuple[int, int]]:
        """
        Locates the character slice [start_idx, end_idx) in full_content
        corresponding to target_code.

        Strategy:
          0. Line-hint anchored search if line_hint is provided (disambiguates duplicate blocks).
          1. Exact substring match.
          2. Exact stripped match (ignoring leading/trailing blank lines).
          3. Whitespace-flexible regex match (allowing flexible indentation/spacing).
        """
        target = target_code.strip("\r\n")
        if not target:
            return None

        norm_content = full_content.replace("\r\n", "\n")
        norm_target = target.replace("\r\n", "\n")

        # 0. Prioritize line hint if provided (disambiguates identical code blocks in file)
        if line_hint and line_hint > 0:
            hint_idx = line_hint - 1
            candidates = []
            cur_pos = 0
            while True:
                pos = norm_content.find(norm_target, cur_pos)
                if pos == -1:
                    break
                match_line = norm_content[:pos].count("\n")
                candidates.append((abs(match_line - hint_idx), pos))
                cur_pos = pos + 1

            if candidates:
                candidates.sort(key=lambda x: x[0])
                best_pos = candidates[0][1]
                orig_start = cls._map_normalized_index_to_original(full_content, norm_content, best_pos)
                orig_end = cls._map_normalized_index_to_original(full_content, norm_content, best_pos + len(norm_target))
                return orig_start, orig_end

        # 1. Exact match
        idx = full_content.find(target)
        if idx != -1:
            return idx, idx + len(target)

        # 2. Line-ending normalized match (handle CRLF vs LF differences in LLM output)
        idx = norm_content.find(norm_target)
        if idx != -1:
            orig_start = cls._map_normalized_index_to_original(full_content, norm_content, idx)
            orig_end = cls._map_normalized_index_to_original(full_content, norm_content, idx + len(norm_target))
            return orig_start, orig_end

        # 3. Whitespace-flexible regex match
        lines = [line.strip() for line in norm_target.splitlines() if line.strip()]
        if lines:
            pattern_parts = [re.escape(l) for l in lines]
            regex_pattern = r'\s*'.join(pattern_parts)
            match = re.search(regex_pattern, norm_content)
            if match:
                orig_start = cls._map_normalized_index_to_original(full_content, norm_content, match.start())
                orig_end = cls._map_normalized_index_to_original(full_content, norm_content, match.end())
                return orig_start, orig_end

        return None

    @staticmethod
    def _map_normalized_index_to_original(original: str, normalized: str, norm_index: int) -> int:
        """Helper to map a character index in a normalized \n string back to a \r\n original."""
        orig_idx = 0
        norm_idx = 0
        while norm_idx < norm_index and orig_idx < len(original):
            if original[orig_idx:orig_idx + 2] == "\r\n":
                orig_idx += 2
                norm_idx += 1
            else:
                orig_idx += 1
                norm_idx += 1
        return orig_idx

    # ------------------------------------------------------------------
    # Syntax Validation
    # ------------------------------------------------------------------

    @classmethod
    def validate_syntax(cls, file_path: Any, code: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Validates the syntax of the modified code based on file extension.
        Accepts (file_path, code) or (code, file_path).
        Returns (is_valid, error_message).
        """
        # Flexible argument ordering
        if isinstance(file_path, str) and code is not None:
            if ("\n" in file_path or len(file_path) > 40) and Path(code).suffix:
                file_path, code = code, file_path

        path_obj = Path(file_path)
        suffix = path_obj.suffix.lower()
        code_str = code or ""

        # Python syntax validation via AST
        if suffix == ".py":
            try:
                ast.parse(code_str, filename=str(path_obj))
                return True, None
            except SyntaxError as e:
                err_msg = f"Python syntax error on line {e.lineno}: {e.msg}"
                return False, err_msg
            except Exception as e:
                return False, f"Python syntax validation failed: {e}"

        # JSON validation
        if suffix == ".json":
            try:
                json.loads(code_str)
                return True, None
            except Exception as e:
                return False, f"JSON syntax error: {e}"

        # C / C++ / Java / JS / TS / Rust / Go / C# basic bracket & brace balance check
        if suffix in (".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".swift"):
            valid, err = cls._check_bracket_balance(code_str)
            if not valid:
                return False, err

        return True, None

        return True, None

    @staticmethod
    def _check_bracket_balance(code: str) -> Tuple[bool, Optional[str]]:
        """Verifies that curly braces, brackets, and parentheses are balanced."""
        stack = []
        pairs = {')': '(', '}': '{', ']': '['}
        line_num = 1
        in_string = False
        str_char = ''
        in_single_comment = False
        in_multi_comment = False

        i = 0
        n = len(code)
        while i < n:
            ch = code[i]
            if ch == '\n':
                line_num += 1
                in_single_comment = False
                i += 1
                continue

            if in_single_comment:
                i += 1
                continue

            if in_multi_comment:
                if ch == '*' and i + 1 < n and code[i + 1] == '/':
                    in_multi_comment = False
                    i += 2
                    continue
                i += 1
                continue

            # Check comments
            if not in_string:
                if ch == '/' and i + 1 < n and code[i + 1] == '/':
                    in_single_comment = True
                    i += 2
                    continue
                if ch == '/' and i + 1 < n and code[i + 1] == '*':
                    in_multi_comment = True
                    i += 2
                    continue

            # Check strings
            if ch in ('"', "'", '`'):
                if not in_string:
                    in_string = True
                    str_char = ch
                elif ch == str_char and (i == 0 or code[i - 1] != '\\'):
                    in_string = False
                i += 1
                continue

            if in_string:
                i += 1
                continue

            if ch in '({[':
                stack.append((ch, line_num))
            elif ch in ')}]':
                if not stack:
                    return False, f"Unmatched closing '{ch}' near line {line_num}"
                top, top_line = stack.pop()
                if pairs[ch] != top:
                    return False, f"Mismatched bracket: expected '{pairs[ch]}' (opened line {top_line}) but found '{ch}' near line {line_num}"

            i += 1

        if stack:
            top, top_line = stack[-1]
            return False, f"Unclosed '{top}' opened on line {top_line}"

        return True, None

    # ------------------------------------------------------------------
    # Apply Patch
    # ------------------------------------------------------------------

    def apply_patch(self, patch: TargetedPatch) -> Tuple[bool, str, Optional[str]]:
        """
        Applies a targeted semantic patch safely.

        Execution Pipeline:
          1. Read current content and detect EOL.
          2. Locate target slice.
          3. Generate unified diff.
          4. Create backup (.bak).
          5. Perform targeted replacement.
          6. Validate syntax.
          7. If syntax fails -> rollback to backup and return error.
          8. Write file preserving original line endings.
          9. Record in undo stack.

        Returns (success: bool, message: str, diff: Optional[str]).
        """
        path = patch.file_path
        if not path.is_file():
            return False, f"File not found: {path}", None

        original_content, eol = self.read_file_with_eol(path)

        # Locate target code in file
        span = self.locate_target_block(original_content, patch.target_code, patch.line_hint)
        if span is None:
            snippet = patch.target_code.strip()[:80]
            return False, f"Could not find matching code snippet in {path.name}: '{snippet}'", None

        start_idx, end_idx = span

        # Construct modified content based on action type
        if patch.action_type == "insert_before":
            modified_content = original_content[:start_idx] + patch.replacement_code + original_content[start_idx:]
        elif patch.action_type == "insert_after":
            modified_content = original_content[:end_idx] + patch.replacement_code + original_content[end_idx:]
        elif patch.action_type == "delete":
            modified_content = original_content[:start_idx] + original_content[end_idx:]
        else:  # "replace" (default)
            modified_content = original_content[:start_idx] + patch.replacement_code + original_content[end_idx:]

        # Generate unified diff
        diff = self.generate_unified_diff(original_content, modified_content, path.name)
        patch.diff = diff

        # Create backup (.bak) on disk
        bak_path = path.with_suffix(path.suffix + ".bak")
        try:
            shutil.copy2(path, bak_path)
        except Exception as e:
            logger.warning(f"Could not create disk backup: {e}")

        # Validate syntax before committing to disk
        is_valid, syntax_error = self.validate_syntax(path, modified_content)
        if not is_valid:
            logger.error(f"Syntax validation failed for patch on {path.name}: {syntax_error}")
            return False, f"Edit cancelled due to syntax error: {syntax_error}", diff

        # Write modified content preserving file line endings
        try:
            self.write_file_preserving_eol(path, modified_content, eol)
        except Exception as e:
            # Restore from backup
            if bak_path.is_file():
                shutil.copy2(bak_path, path)
            return False, f"Failed writing changes to {path.name}: {e}", None

        # Record in in-memory undo stack
        self._undo_history.append({
            "path": path,
            "original_content": original_content,
            "modified_content": modified_content,
            "diff": diff,
            "explanation": patch.explanation or f"Patched {path.name}",
            "eol": eol
        })

        logger.info(f"Targeted patch successfully applied to {path.name}")
        summary = patch.explanation or f"Applied targeted edit to {path.name}."
        return True, summary, diff

    # ------------------------------------------------------------------
    # Undo Support
    # ------------------------------------------------------------------

    def undo_last_patch(self, file_path: Optional[Any] = None) -> Tuple[bool, str]:
        """
        Reverts the last applied patch from the in-memory undo stack or .bak backup.
        """
        self.last_reverted_path = None
        target_path: Optional[Path] = None
        if file_path:
            try:
                target_path = Path(file_path)
            except Exception:
                target_path = None

        if self._undo_history:
            # If a specific file is requested, find the most recent patch for it
            target_entry = None
            if target_path:
                for i in range(len(self._undo_history) - 1, -1, -1):
                    entry_path = self._undo_history[i]["path"]
                    try:
                        if entry_path.resolve() == target_path.resolve():
                            target_entry = self._undo_history.pop(i)
                            break
                    except Exception:
                        if str(entry_path).lower() == str(target_path).lower():
                            target_entry = self._undo_history.pop(i)
                            break

            # If not matched to specific file but specific file had no entry, check if that file has .bak
            if not target_entry and target_path:
                bak = target_path.with_suffix(target_path.suffix + ".bak")
                if bak.is_file():
                    shutil.copy2(bak, target_path)
                    self.last_reverted_path = target_path
                    logger.info(f"Restored {target_path.name} from .bak file.")
                    return True, f"Reverted {target_path.name} from backup."

            # Otherwise revert the most recent entry from the global undo history
            if not target_entry and self._undo_history:
                target_entry = self._undo_history.pop()

            if target_entry:
                path = target_entry["path"]
                orig = target_entry["original_content"]
                eol = target_entry["eol"]
                self.write_file_preserving_eol(path, orig, eol)
                self.last_reverted_path = path
                logger.info(f"Reverted last patch on {path.name} from undo stack.")
                return True, f"Reverted previous code change in {path.name}."

        # Fallback to .bak file on disk
        if target_path:
            bak = target_path.with_suffix(target_path.suffix + ".bak")
            if bak.is_file():
                shutil.copy2(bak, target_path)
                self.last_reverted_path = target_path
                logger.info(f"Restored {target_path.name} from .bak file.")
                return True, f"Reverted {target_path.name} from backup."

        return False, "No previous code changes to undo."

    def clear_history(self) -> None:
        self._undo_history.clear()


# Global patch engine singleton
code_patch_engine = CodePatchEngine()
