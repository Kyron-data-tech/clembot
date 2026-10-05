import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from app.editor.base import EditorAdapter
from app.logging.logger import logger


class GenericWindowsEditorAdapter(EditorAdapter):
    """
    Fallback editor adapter for standard Windows editors (Notepad, Notepad++, etc.).
    Performs file-level reading, writing, and backup management.
    """

    def __init__(self, current_file: Optional[Path] = None):
        self.current_file = current_file

    def is_available(self) -> bool:
        return True

    def get_active_file(self) -> Optional[Path]:
        return self.current_file

    def read_document(self, file_path: Optional[Path] = None) -> Optional[str]:
        target = file_path or self.current_file
        if target and target.is_file():
            try:
                return target.read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"Generic editor read error: {e}")
        return None

    def jump_to_line(self, line_number: int) -> bool:
        # Generic editors don't have standard line jump IPC, open via notepad or notepad++
        if self.current_file:
            # Notepad++ supports -n<line>
            npp = shutil.which("notepad++.exe")
            if npp:
                subprocess.Popen([npp, f"-n{line_number}", str(self.current_file)])
                return True
            # Cross-platform: open the file with its default application
            if hasattr(os, "startfile"):
                os.startfile(str(self.current_file))
            elif sys.platform == "darwin":
                subprocess.Popen(["/usr/bin/open", str(self.current_file)])
            else:
                subprocess.Popen(["xdg-open", str(self.current_file)])
            return True
        return False

    def apply_edit(
        self,
        file_path: Path,
        start_line: int,
        end_line: int,
        new_text: str,
        start_col: int = 0,
        end_col: int = 0
    ) -> bool:
        if not file_path.is_file():
            return False

        try:
            bak_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, bak_path)

            lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
            idx_start = max(0, start_line - 1)
            idx_end = min(len(lines), end_line)

            new_lines = new_text if new_text.endswith("\n") else new_text + "\n"
            lines[idx_start:idx_end] = [new_lines]

            file_path.write_text("".join(lines), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Generic apply_edit failed: {e}")
            return False

    def save(self) -> bool:
        return True

    def run_code(self) -> bool:
        if self.current_file and self.current_file.suffix == ".py":
            try:
                from app.platform_layer import platform_adapter
                platform_adapter.run_user_code_in_terminal(self.current_file)
                return True
            except Exception:
                # Fallback: run directly with sys.executable
                subprocess.Popen(
                    [sys.executable, str(self.current_file)],
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                return True
        return False

    def undo(self) -> bool:
        if self.current_file:
            bak = self.current_file.with_suffix(self.current_file.suffix + ".bak")
            if bak.is_file():
                shutil.copy2(bak, self.current_file)
                return True
        return False
