import ast
import difflib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.logging.logger import logger


@dataclass
class CodeEditProposal:
    file_path: Path
    start_line: int
    end_line: int
    original_code: str
    proposed_code: str
    diff: str
    explanation: str
    is_major: bool = False


class CodeIntelligenceEngine:
    """
    Intelligent code reasoning, AST inspection, diff generation, and safe code editing.
    Ensures targeted, non-destructive modifications with backup and user confirmation.
    """

    @staticmethod
    def generate_unified_diff(original_text: str, modified_text: str, filename: str = "file") -> str:
        """Generates a standard unified diff between original and modified code."""
        orig_lines = original_text.splitlines(keepends=True)
        mod_lines = modified_text.splitlines(keepends=True)

        diff = difflib.unified_diff(
            orig_lines,
            mod_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm=""
        )
        return "".join(diff)

    @staticmethod
    def find_python_function_range(source_code: str, function_name: str) -> Optional[Tuple[int, int, str]]:
        """
        Locates the line range (start_line, end_line) of a function in Python code using AST.
        Returns (start_line, end_line, function_source) (1-indexed).
        """
        try:
            tree = ast.parse(source_code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.lower() == function_name.lower():
                        start_line = node.lineno
                        end_line = getattr(node, 'end_lineno', start_line + 10)
                        lines = source_code.splitlines(keepends=True)
                        func_code = "".join(lines[start_line - 1:end_line])
                        return start_line, end_line, func_code
        except Exception as e:
            logger.debug(f"AST parse failed, fallback to regex search: {e}")

        # Regex fallback
        pattern = rf'^(?:async\s+)?def\s+{re.escape(function_name)}\s*\('
        lines = source_code.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if re.search(pattern, line):
                start_line = i + 1
                # Find end of indented block
                base_indent = len(line) - len(line.lstrip())
                end_line = start_line
                for j in range(i + 1, len(lines)):
                    sub_line = lines[j]
                    if not sub_line.strip():
                        continue
                    indent = len(sub_line) - len(sub_line.lstrip())
                    if indent <= base_indent:
                        break
                    end_line = j + 1
                func_code = "".join(lines[start_line - 1:end_line])
                return start_line, end_line, func_code

        return None

    @classmethod
    def propose_function_rename(
        cls,
        file_path: Path,
        old_name: str,
        new_name: str
    ) -> Optional[CodeEditProposal]:
        """
        Proposes renaming a function definition and its calls within the file.
        """
        if not file_path.is_file():
            return None

        original = file_path.read_text(encoding="utf-8")
        # Replace occurrences as identifier
        pattern = rf'\b{re.escape(old_name)}\b'
        modified, count = re.subn(pattern, new_name, original)

        if count == 0:
            return None

        diff = cls.generate_unified_diff(original, modified, file_path.name)
        return CodeEditProposal(
            file_path=file_path,
            start_line=1,
            end_line=len(original.splitlines()),
            original_code=original,
            proposed_code=modified,
            diff=diff,
            explanation=f"Rename function '{old_name}' to '{new_name}' ({count} occurrence{'s' if count != 1 else ''}).",
            is_major=count > 3
        )

    @classmethod
    def propose_exception_handling_at_line(
        cls,
        file_path: Path,
        target_line: int,
        line_count: int = 1
    ) -> Optional[CodeEditProposal]:
        """
        Wraps code lines around target_line in a try...except Exception block.
        """
        if not file_path.is_file():
            return None

        lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if target_line < 1 or target_line > len(lines):
            return None

        idx_start = target_line - 1
        idx_end = min(len(lines), idx_start + line_count)

        target_chunk = "".join(lines[idx_start:idx_end])
        # Detect indentation
        first_line = lines[idx_start]
        indent = " " * (len(first_line) - len(first_line.lstrip()))
        extra_indent = "    "

        indented_lines = []
        for line in lines[idx_start:idx_end]:
            if line.strip():
                indented_lines.append(f"{extra_indent}{line}")
            else:
                indented_lines.append(line)

        wrapped = (
            f"{indent}try:\n"
            f"{''.join(indented_lines)}"
            f"{indent}except Exception as e:\n"
            f"{indent}    logger.error(f'Error at line {target_line}: {{e}}')\n"
        )

        mod_lines = list(lines)
        mod_lines[idx_start:idx_end] = [wrapped]
        modified_full = "".join(mod_lines)

        diff = cls.generate_unified_diff("".join(lines), modified_full, file_path.name)
        return CodeEditProposal(
            file_path=file_path,
            start_line=target_line,
            end_line=idx_end,
            original_code=target_chunk,
            proposed_code=wrapped,
            diff=diff,
            explanation=f"Wrap lines {target_line}–{idx_end} in a try-except error handling block.",
            is_major=False
        )

    @classmethod
    def inspect_active_context(cls, file_path: Path, line_number: Optional[int] = None) -> Dict[str, Any]:
        """
        Inspects the active file and extracts the enclosing function/class,
        signature, and surrounding code window (1-indexed).
        """
        if not file_path.is_file():
            return {"file": str(file_path), "exists": False}

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="cp1252", errors="replace")

        lines = content.splitlines()
        total_lines = len(lines)
        target_line = max(1, min(line_number or 1, total_lines))

        # Context window: up to 15 lines before and after
        start_win = max(0, target_line - 15)
        end_win = min(total_lines, target_line + 15)
        window_lines = lines[start_win:end_win]

        enclosing_symbol = None
        symbol_type = None

        # If Python, use AST to find enclosing function/class
        if file_path.suffix.lower() == ".py":
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        start = getattr(node, "lineno", 0)
                        end = getattr(node, "end_lineno", start + 20)
                        if start <= target_line <= end:
                            enclosing_symbol = node.name
                            symbol_type = "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class"
            except Exception:
                pass

        # Regex fallback for other languages (JS/TS/C/Go/Java)
        if not enclosing_symbol:
            for i in range(target_line - 1, -1, -1):
                l = lines[i]
                fn_match = re.search(r'(?:def|function|class|async\s+def|async\s+function)\s+([a-zA-Z_]\w*)', l)
                if fn_match:
                    enclosing_symbol = fn_match.group(1)
                    symbol_type = "function" if "class" not in l else "class"
                    break

        return {
            "file": str(file_path),
            "file_name": file_path.name,
            "total_lines": total_lines,
            "target_line": target_line,
            "enclosing_symbol": enclosing_symbol,
            "symbol_type": symbol_type,
            "snippet": "\n".join(window_lines),
            "start_line": start_win + 1,
            "end_line": end_win
        }

    @classmethod
    def find_symbols_in_workspace(
        cls,
        workspace_path: Path,
        symbol_query: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Searches source files in the workspace for symbol definitions
        matching symbol_query. Bounded and skips build/cache directories.
        """
        if not workspace_path.is_dir():
            return []

        q = symbol_query.strip().lower()
        if not q:
            return []

        # Common code extensions
        code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".html", ".css"}
        ignored_dirs = {"node_modules", ".git", ".vscode", "__pycache__", "venv", ".venv", "dist", "build"}

        results: List[Dict[str, Any]] = []

        try:
            for dirpath, dirnames, filenames in os.walk(str(workspace_path)):
                dirnames[:] = [d for d in dirnames if d.lower() not in ignored_dirs and not d.startswith(".")]

                for fn in filenames:
                    p = Path(dirpath) / fn
                    if p.suffix.lower() not in code_exts:
                        continue

                    try:
                        raw = p.read_bytes()
                        text = raw.decode("utf-8", errors="ignore")
                    except Exception:
                        continue

                    lines = text.splitlines()
                    for idx, line in enumerate(lines, 1):
                        # Match function/class/variable/route definition
                        if q in line.lower() and re.search(r'\b(?:def|class|function|const|let|var|route|url|path)\b', line, re.IGNORECASE):
                            results.append({
                                "file": str(p),
                                "file_name": p.name,
                                "line_number": idx,
                                "line_content": line.strip()
                            })
                            if len(results) >= max_results:
                                return results
        except Exception as e:
            logger.debug(f"Workspace symbol search error: {e}")

        return results

    @classmethod
    def extract_file_outline(cls, file_path: Path) -> List[str]:
        """Returns top-level function and class signatures in the file."""
        if not file_path.is_file():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        outline = []
        if file_path.suffix.lower() == ".py":
            try:
                tree = ast.parse(content)
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = [a.arg for a in node.args.args]
                        outline.append(f"def {node.name}({', '.join(args)}) [line {node.lineno}]")
                    elif isinstance(node, ast.ClassDef):
                        outline.append(f"class {node.name} [line {node.lineno}]")
                return outline
            except Exception:
                pass

        # Regex outline for non-Python or fallback
        for idx, line in enumerate(content.splitlines(), 1):
            m = re.search(r'^\s*(?:def|class|function|async\s+def)\s+([a-zA-Z_]\w*\s*\([^)]*\))', line)
            if m:
                outline.append(f"{m.group(0).strip()} [line {idx}]")

        return outline

    @classmethod
    def apply_proposal(cls, proposal: CodeEditProposal) -> bool:
        """
        Safely applies a proposal by creating a backup (.bak) first and writing updated code.
        """
        try:
            target = proposal.file_path
            bak_path = target.with_suffix(target.suffix + ".bak")
            shutil.copy2(target, bak_path)

            from app.editor.code_patch_engine import code_patch_engine
            orig_text, eol = code_patch_engine.read_file_with_eol(target)
            code_patch_engine.write_file_preserving_eol(target, proposal.proposed_code, eol)
            code_patch_engine._undo_history.append({
                "path": target,
                "original_content": orig_text,
                "modified_content": proposal.proposed_code,
                "diff": proposal.diff,
                "explanation": proposal.explanation,
                "eol": eol
            })
            logger.info(f"Successfully applied code edit to {target}. Backup at {bak_path.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply code proposal: {e}")
            return False
