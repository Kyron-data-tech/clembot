import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import send2trash

from app.config.settings import settings
from app.filesystem.paths import WindowsPathResolver
from app.logging.logger import logger


class FileSystemService:
    """
    Robust, safe cross-platform filesystem operations.
    Enforces non-destructive defaults (Send2Trash to Recycle Bin / macOS Trash) and
    dynamic path resolution.  Works on Windows and macOS.
    """

    def __init__(self):
        self.resolver = WindowsPathResolver()

    def resolve(self, raw_path: Union[str, Path], base_context: Optional[Path] = None) -> Path:
        if isinstance(raw_path, Path):
            return raw_path
        return self.resolver.resolve_path(raw_path, base_context)

    def open_folder(self, raw_path: Union[str, Path]) -> str:
        """Opens the folder in Windows File Explorer."""
        path_str = str(raw_path).strip()
        if path_str.startswith("::{") or path_str.startswith("shell:"):
            target_shell = path_str if path_str.startswith("shell:") else f"shell:{path_str}"
            import subprocess
            subprocess.Popen(["explorer.exe", target_shell])
            return "Opening system folder."

        target = self.resolve(raw_path)
        if not target.exists():
            raise FileNotFoundError(f"Folder not found: {target}")
        if not target.is_dir():
            target = target.parent

        if hasattr(os, "startfile"):
            os.startfile(str(target))
        else:
            import subprocess
            subprocess.Popen(["open", str(target)])
        return f"Opening {target.name or str(target)}."

    def open_file(self, raw_path: Union[str, Path]) -> str:
        """Opens a file with its default application."""
        target = self.resolve(raw_path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {target}")

        if hasattr(os, "startfile"):
            os.startfile(str(target))
        else:
            import subprocess
            subprocess.Popen(["open", str(target)])
        return f"Opening {target.name}."

    def create_folder(self, raw_path: Union[str, Path], base_context: Optional[Path] = None) -> str:
        """Creates a new folder at the resolved path."""
        target = self.resolve(raw_path, base_context)
        if target.exists():
            raise FileExistsError(f"A folder or file already exists at '{target}'.")

        target.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created folder: {target}")
        return f"Done. Created folder '{target.name}' at {target.parent}."

    def create_file(self, raw_path: Union[str, Path], content: str = "", base_context: Optional[Path] = None) -> str:
        """Creates a new text file at the resolved path."""
        target = self.resolve(raw_path, base_context)
        if target.exists():
            raise FileExistsError(f"A file already exists at '{target}'.")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
        logger.info(f"Created file: {target}")
        return f"Done. Created file '{target.name}'."

    def delete_item(self, raw_path: Union[str, Path], permanent: bool = False) -> str:
        """
        Deletes a file or directory.
        Defaults to sending to Windows Recycle Bin via send2trash so it can be restored.
        """
        target = self.resolve(raw_path)
        if not target.exists():
            raise FileNotFoundError(f"Cannot delete: '{target}' does not exist.")

        name = target.name
        is_directory = target.is_dir()

        if permanent or not settings.send_to_recycle_bin:
            if is_directory:
                shutil.rmtree(target)
            else:
                target.unlink()
            return f"Permanently deleted '{name}'."
        else:
            # Send to Windows Recycle Bin
            send2trash.send2trash(str(target))
            return f"Moved '{name}' to the Windows Recycle Bin."

    def rename_item(self, source_raw: Union[str, Path], new_name: str) -> str:
        """Renames a file or folder."""
        source = self.resolve(source_raw)
        if not source.exists():
            raise FileNotFoundError(f"Cannot rename: '{source}' does not exist.")

        # Determine target path
        if "\\" in new_name or "/" in new_name:
            destination = self.resolve(new_name)
        else:
            destination = source.parent / new_name

        if destination.exists():
            raise FileExistsError(f"An item already exists at '{destination}'.")

        source.rename(destination)
        logger.info(f"Renamed {source} -> {destination}")
        return f"Renamed '{source.name}' to '{destination.name}'."

    def move_item(self, source_raw: Union[str, Path], destination_raw: Union[str, Path]) -> str:
        """Moves a file or folder to a destination directory."""
        source = self.resolve(source_raw)
        if not source.exists():
            raise FileNotFoundError(f"Cannot move: '{source}' does not exist.")

        destination = self.resolve(destination_raw)
        if destination.is_dir():
            dest_file = destination / source.name
        else:
            dest_file = destination

        if dest_file.exists():
            raise FileExistsError(f"Destination already contains an item named '{dest_file.name}'.")

        shutil.move(str(source), str(dest_file))
        logger.info(f"Moved {source} -> {dest_file}")
        return f"Moved '{source.name}' to '{dest_file.parent.name}'."

    def copy_item(self, source_raw: Union[str, Path], destination_raw: Union[str, Path]) -> str:
        """Copies a file or folder to a destination directory."""
        source = self.resolve(source_raw)
        if not source.exists():
            raise FileNotFoundError(f"Cannot copy: '{source}' does not exist.")

        destination = self.resolve(destination_raw)
        if destination.is_dir():
            dest_file = destination / source.name
        else:
            dest_file = destination

        if dest_file.exists():
            raise FileExistsError(f"Destination already contains '{dest_file.name}'.")

        if source.is_dir():
            shutil.copytree(str(source), str(dest_file))
        else:
            shutil.copy2(str(source), str(dest_file))

        logger.info(f"Copied {source} -> {dest_file}")
        return f"Copied '{source.name}' to '{dest_file.parent.name}'."

    def duplicate_item(self, source_raw: Union[str, Path]) -> str:
        """Duplicates a file or folder with ' - Copy' suffix."""
        source = self.resolve(source_raw)
        if not source.exists():
            raise FileNotFoundError(f"Item not found: {source}")

        parent = source.parent
        stem = source.stem
        suffix = source.suffix
        is_dir = source.is_dir()

        counter = 1
        while True:
            copy_name = f"{stem} - Copy{'' if counter == 1 else f' ({counter})'}{suffix}"
            dest = parent / copy_name
            if not dest.exists():
                break
            counter += 1

        if is_dir:
            shutil.copytree(str(source), str(dest))
        else:
            shutil.copy2(str(source), str(dest))

        return f"Created copy '{dest.name}'."

    def list_directory(self, raw_path: Union[str, Path]) -> Tuple[str, Dict[str, List[str]]]:
        """
        Inspects directory contents and returns both a natural language summary and structured list.
        Example response: "Downloads contains 12 files and 3 folders."
        """
        target = self.resolve(raw_path)
        if not target.exists():
            raise FileNotFoundError(f"Directory not found: {target}")
        if not target.is_dir():
            raise NotADirectoryError(f"'{target}' is not a directory.")

        try:
            entries = list(target.iterdir())
        except PermissionError:
            raise PermissionError(f"Permission denied accessing {target}")

        files = [e.name for e in entries if e.is_file()]
        folders = [e.name for e in entries if e.is_dir()]

        summary = f"{target.name or str(target)} contains {len(files)} file{'s' if len(files) != 1 else ''} and {len(folders)} folder{'s' if len(folders) != 1 else ''}."
        
        # Add quick preview if small
        if entries:
            sample_items = [e.name for e in entries[:6]]
            sample_text = ", ".join(sample_items)
            if len(entries) > 6:
                sample_text += f", and {len(entries) - 6} more"
            summary += f" Including: {sample_text}."

        return summary, {"files": files, "folders": folders}

    def count_items_in_directory(self, raw_path: Union[str, Path]) -> int:
        """Returns the recursive count of items inside a directory (for safety check)."""
        target = self.resolve(raw_path)
        if not target.is_dir():
            return 1
        count = 0
        try:
            for _, dirs, files in os.walk(str(target)):
                count += len(dirs) + len(files)
                if count > 500:  # Bound to avoid freeze on massive trees
                    break
        except Exception:
            pass
        return count
