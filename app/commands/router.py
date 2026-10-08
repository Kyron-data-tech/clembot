import re
import sys
from pathlib import Path
from typing import Optional

from app.commands.friendly_errors import friendly_errors
from app.core.models import ActionResult, AgentAction
from app.editor.code_intelligence import CodeIntelligenceEngine
from app.editor.vscode_adapter import VSCodeAdapter
from app.filesystem.search import FileSearchService
from app.filesystem.service import FileSystemService
from app.logging.logger import logger
from app.platform_layer import KeyMap, platform_adapter


class _RouterClipboardAdapter:
    def clear(self) -> str:
        return platform_adapter.clear_clipboard()


class _RouterInputAdapter:
    def copy(self) -> None:
        platform_adapter.send_hotkey(*KeyMap.copy())

    def paste(self) -> None:
        platform_adapter.send_hotkey(*KeyMap.paste())

    def select_all(self) -> None:
        platform_adapter.send_hotkey(*KeyMap.select_all())

    def undo(self) -> None:
        platform_adapter.send_hotkey(*KeyMap.undo())

    def redo(self) -> None:
        platform_adapter.send_hotkey(*KeyMap.redo())

    def save(self) -> None:
        platform_adapter.send_hotkey(*KeyMap.save())


class ActionRouter:
    """
    Executes AgentAction objects by routing them to the appropriate platform subsystem.
    Returns an ActionResult detailing outcome and response.
    """

    def __init__(self):
        self.platform = platform_adapter
        self.fs = getattr(self.platform, "_fs_service", None) or FileSystemService()
        self.search = getattr(self.platform, "_search_service", None) or FileSearchService()
        self.apps = getattr(self.platform, "_app_catalog", self.platform)
        self.windows = getattr(self.platform, "_window_mgr", self.platform)
        self.browser = getattr(self.platform, "_browser_ctrl", self.platform)
        self.clipboard = _RouterClipboardAdapter()
        self.input_adapter = _RouterInputAdapter()
        self.vscode = VSCodeAdapter()
        self.code_engine = CodeIntelligenceEngine()

    def _resolve_target_path(self, target: str, context_base: Optional[Path] = None) -> Optional[Path]:
        """Resolves target file/folder cross-platform via platform adapter and fallback paths."""
        if not target:
            return None
        # 1. Platform adapter spoken/alias resolution
        try:
            resolved = self.platform.resolve_spoken_path(target, context_base=context_base)
            if resolved and resolved.exists():
                return resolved
        except Exception:
            pass

        # 2. WindowsPathResolver (for Windows and unit-test mock compatibility)
        try:
            from app.filesystem.paths import WindowsPathResolver
            res = WindowsPathResolver.resolve(target, context_base=context_base)
            if res:
                return res
        except Exception:
            pass

        # 3. Direct path
        p = Path(target)
        if p.exists() or p.is_file() or p.is_dir():
            return p

        # 4. Context base
        if context_base and (context_base / target).exists():
            return context_base / target

        # 5. Standard folders
        try:
            std = self.platform.get_standard_folders()
            for root in std.values():
                cand = root / target
                if cand.exists():
                    return cand
        except Exception:
            pass

        # 6. Fallback to fs resolve
        try:
            cand = self.fs.resolve(target, base_context=context_base)
            if cand:
                return cand
        except Exception:
            pass

        return Path(target)



    def execute(self, action: AgentAction, context_base: Optional[Path] = None) -> ActionResult:
        act_type = action.type.lower()
        logger.info(f"Routing action: {act_type} (params: {action.model_dump(exclude_none=True)})")

        try:
            # 1. Filesystem actions
            if act_type == "open_folder":
                raw_folder = (action.path or "Downloads").strip()
                clean_folder = re.sub(r'^(?:(?:the|my)\s+)?(?:folder|directory|project|workspace)\s+', '', raw_folder, flags=re.IGNORECASE).strip() or raw_folder
                clean_folder = re.sub(r'\s+(?:folder|directory|project|workspace)$', '', clean_folder, flags=re.IGNORECASE).strip() or clean_folder
                clean_folder = clean_folder.strip("'\" ")

                # 1. System shell target (e.g. ::{...})
                if clean_folder.startswith("::{") or clean_folder.startswith("shell:"):
                    msg = self.fs.open_folder(clean_folder)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

                # 1b. Direct existing absolute folder
                try:
                    direct_dir = Path(clean_folder)
                    if direct_dir.is_absolute() and direct_dir.is_dir():
                        if self.vscode.get_active_file() or self.vscode.get_workspace() or self.platform.is_app_running("vscode"):
                            self.vscode.open_file(direct_dir)
                            return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                                message=f"Opened folder '{direct_dir.name}' in VS Code.")
                        else:
                            msg = self.fs.open_folder(direct_dir)
                            return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)
                except Exception:
                    pass

                # 2. Check if it exists in the active VS Code workspace
                ws_folder = self.vscode.find_in_workspace(clean_folder, search_files=False, search_folders=True)
                if ws_folder and ws_folder.is_dir():
                    self.vscode.open_file(ws_folder)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                        message=f"Opened folder '{ws_folder.name}' in VS Code.")

                # 3. Regular filesystem folder resolution
                try:
                    msg = self.fs.open_folder(clean_folder)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)
                except FileNotFoundError:
                    found = self.search.find_first(clean_folder)
                    if found and found.is_dir():
                        msg = self.fs.open_folder(found)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Found and opened folder '{found.name}'.")
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message=f"I couldn't find folder '{clean_folder}'.")

            elif act_type == "open_file":
                target_str = (action.path or "").strip()
                lower_target = target_str.lower()

                # Named shell shortcuts — always treat as apps, never as files
                if lower_target in ["explorer", "file explorer", "taskmgr", "task manager", "settings", "control"]:
                    msg = self.apps.open_or_activate(target_str)
                    return ActionResult(action_id=action.id, action_type="open_app", success=True, message=msg)

                clean_target = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', target_str, flags=re.IGNORECASE).strip() or target_str

                # Code file extensions that should open in VS Code if VS Code is running or active
                code_exts = {
                    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".txt",
                    ".md", ".c", ".cpp", ".h", ".cs", ".java", ".rs", ".go", ".sh", ".bat",
                    ".ps1", ".yaml", ".yml", ".xml", ".sql", ".ini", ".toml", ".env"
                }

                # 1. First check if it exists in the active VS Code workspace / active file folder
                ws_match = self.vscode.find_in_workspace(clean_target)
                if ws_match and ws_match.exists():
                    self.vscode.open_file(ws_match)
                    item_type = "folder" if ws_match.is_dir() else "file"
                    return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                        message=f"Opened {item_type} '{ws_match.name}' in VS Code.")

                # 2. Check if the target has a file extension or resolves on filesystem
                has_extension = bool(re.search(r'\.[a-zA-Z0-9]{1,6}$', clean_target))
                if has_extension:
                    try:
                        resolved_p = self._resolve_target_path(clean_target, context_base=context_base)
                        if resolved_p and resolved_p.exists():
                            if resolved_p.suffix.lower() in code_exts and (self.vscode.get_active_file() or self.vscode.get_workspace() or self.apps.is_running("vscode")):
                                self.vscode.open_file(resolved_p)
                                return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                                    message=f"Opened '{resolved_p.name}' in VS Code.")
                            else:
                                msg = self.fs.open_file(resolved_p)
                                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)
                        else:
                            raise FileNotFoundError(f"File not found: {clean_target}")
                    except FileNotFoundError:
                        found = self.search.find_first(clean_target)
                        if found and found.is_file():
                            if found.suffix.lower() in code_exts and (self.vscode.get_active_file() or self.vscode.get_workspace() or self.apps.is_running("vscode")):
                                self.vscode.open_file(found)
                                return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                                    message=f"Found and opened '{found.name}' in VS Code.")
                            else:
                                msg = self.fs.open_file(found)
                                return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                                    message=f"Found and opened '{found.name}'.")
                        return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                            message=f"I couldn't find '{clean_target}' on your system.")

                # 3. No extension — could be a file without extension or an app name; try filesystem then app
                try:
                    resolved_p = self._resolve_target_path(clean_target, context_base=context_base)
                    if resolved_p and resolved_p.exists() and resolved_p.is_file():
                        if resolved_p.suffix.lower() in code_exts and (self.vscode.get_active_file() or self.vscode.get_workspace() or self.apps.is_running("vscode")):
                            self.vscode.open_file(resolved_p)
                            return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                                message=f"Opened '{resolved_p.name}' in VS Code.")
                        msg = self.fs.open_file(resolved_p)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)
                    raise FileNotFoundError()

                except FileNotFoundError:
                    try:
                        msg = self.apps.open_or_activate(target_str)
                        return ActionResult(action_id=action.id, action_type="open_app", success=True, message=msg)
                    except Exception:
                        raise

            elif act_type == "create_folder":
                msg = self.fs.create_folder(action.path, context_base)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "create_file":
                msg = self.fs.create_file(action.path, action.text or "", context_base)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "rename_path":
                msg = self.fs.rename_item(action.path, action.destination)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "move_path":
                msg = self.fs.move_item(action.path, action.destination)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "copy_path":
                dest = action.destination or "Desktop"
                msg = self.fs.copy_item(action.path, dest)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "trash_path":
                msg = self.fs.delete_item(action.path)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "list_directory":
                msg, data = self.fs.list_directory(action.path or "Downloads")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg, data=data)

            elif act_type == "find_file":
                found = self.search.find_first(action.query, scope=action.scope)
                if found:
                    self.fs.open_file(found)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Found and opening '{found.name}'.")
                return ActionResult(action_id=action.id, action_type=act_type, success=False, message=f"I couldn't find '{action.query}' in your files.")

            elif act_type == "open_recent_files":
                if sys.platform == "darwin":
                    import subprocess
                    subprocess.Popen(["open", "-a", "Finder"])
                    import time
                    time.sleep(0.2)
                    self.platform.send_hotkey("command", "shift", "f")
                else:
                    self.platform.open_folder("shell:Recent")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opening recent files.")

            elif act_type == "open_latest_download":
                dl_dir = self.platform.get_standard_folders().get("Downloads")
                if dl_dir and dl_dir.exists():
                    files = [p for p in dl_dir.iterdir() if p.is_file()]
                    if files:
                        latest = max(files, key=lambda f: f.stat().st_mtime)
                        self.fs.open_file(latest)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Opening {latest.name}.")
                return ActionResult(action_id=action.id, action_type=act_type, success=False, message="No files found in Downloads.")

            elif act_type == "reveal_in_file_manager":
                p = self._resolve_target_path(action.path)
                is_mac = sys.platform == "darwin"
                if p and p.exists():
                    import subprocess
                    if is_mac:
                        subprocess.Popen(["open", "-R", str(p)])
                    else:
                        subprocess.Popen(["explorer", f"/select,{str(p)}"])
                    msg = "Showing it in Finder." if is_mac else "Showing it in File Explorer."
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)
                return ActionResult(action_id=action.id, action_type=act_type, success=False, message=f"File '{action.path}' not found.")

            elif act_type == "quick_look":
                p = self._resolve_target_path(action.path) if action.path else None
                if p and p.exists():
                    import subprocess
                    subprocess.Popen(["qlmanage", "-p", str(p)])
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Previewing.")
                else:
                    self.platform.send_key("space")
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Previewing.")

            elif act_type == "open_file_with_app":
                p = self._resolve_target_path(action.path)
                app_name = action.app or "notepad"
                if p and p.exists():
                    import subprocess
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", "-a", app_name, str(p)])
                    else:
                        subprocess.Popen([app_name, str(p)], shell=True)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Opening {p.name} in {app_name.capitalize()}.")
                return ActionResult(action_id=action.id, action_type=act_type, success=False, message=f"File '{action.path}' not found.")

            # 2. Application & Window Control
            elif act_type == "open_app":
                raw_target = (action.app or "").strip()
                target = re.sub(r'^(?:(?:the|my)\s+)?(?:folder|directory|project|workspace)\s+', '', raw_target, flags=re.IGNORECASE).strip()
                target = re.sub(r'\s+(?:folder|directory|project|workspace)$', '', target, flags=re.IGNORECASE).strip() or raw_target

                # 1. Exact built-in or catalog match
                norm_t = target.lower()
                is_exact_app = False
                try:
                    if norm_t in self.apps.BUILTIN_APPS or any(norm_t in [a.lower() for a in entry.get("aliases", [])] for entry in self.apps.BUILTIN_APPS.values()):
                        is_exact_app = True
                    elif norm_t in ["explorer", "file explorer", "taskmgr", "task manager", "settings", "control", "cmd", "terminal", "powershell"]:
                        is_exact_app = True
                    else:
                        with self.apps._lock:
                            is_exact_app = self.apps._normalize(norm_t) in self.apps._catalog
                except Exception:
                    pass

                if is_exact_app:
                    try:
                        msg = self.apps.open_or_activate(target)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=str(msg))
                    except Exception as app_err:
                        logger.debug(f"Exact app launch failed: {app_err}")

                # 2. Check if target is a file or folder in the active VS Code workspace / active directory
                ws_match = self.vscode.find_in_workspace(target) or self.vscode.find_in_workspace(raw_target)
                if ws_match and ws_match.exists():
                    self.vscode.open_file(ws_match)
                    item_type = "folder" if ws_match.is_dir() else "file"
                    return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                        message=f"Opened {item_type} '{ws_match.name}' in VS Code.")

                # 3. Try launching or activating the application with fuzzy matching
                try:
                    msg = self.apps.open_or_activate(raw_target)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=str(msg))
                except Exception as app_err:
                    logger.debug(f"App catalog could not launch '{raw_target}': {app_err}")

                # 3. Check if target is an existing folder or drive
                try:
                    resolved_path = self._resolve_target_path(target, context_base=context_base)
                    if resolved_path and resolved_path.exists():

                        code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".txt", ".md"}
                        if resolved_path.is_file() and resolved_path.suffix.lower() in code_exts and (self.vscode.get_active_file() or self.vscode.get_workspace() or self.apps.is_running("vscode")):
                            self.vscode.open_file(resolved_path)
                            msg = f"Opened '{resolved_path.name}' in VS Code."
                        elif resolved_path.is_dir():
                            msg = self.fs.open_folder(resolved_path)
                        else:
                            msg = self.fs.open_file(resolved_path)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)
                except Exception as path_err:
                    logger.debug(f"Path resolver could not open '{target}': {path_err}")

                # 3. Search for matching file or folder in user directories
                found = self.search.find_first(target)
                if found and found.exists():
                    if found.is_dir():
                        msg = self.fs.open_folder(found)
                    else:
                        msg = self.fs.open_file(found)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Found and opened '{found.name}'.")

                # 4. Check if target is a web destination
                dest_msg = self.browser.open_web_destination(target)
                if dest_msg:
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=dest_msg)

                # 5. Fallback: Search the web
                search_msg = self.browser.search_web(target)
                return ActionResult(action_id=action.id, action_type="web_search", success=True, message=f"Couldn't find '{target}' locally. {search_msg}")

            elif act_type == "close_app":
                app_target = (action.app or "").strip()
                # If target is actually a file, route directly to close_file
                if app_target.lower() in ["this file", "the file", "file", "current file", "active file", "file in vscode", "vscode file", "file vscode"] or re.search(r'\.[a-zA-Z0-9]{1,5}$', app_target):
                    msg = self.vscode.close_file(app_target if re.search(r'\.[a-zA-Z0-9]{1,5}$', app_target) else None)
                else:
                    msg = self.apps.close_app(app_target)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_minimize":
                msg = self.windows.minimize_current()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_maximize":
                msg = self.windows.maximize_current()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_restore":
                msg = self.windows.restore_current()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_close":
                msg = self.windows.close_current()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_snap_left":
                msg = self.windows.snap_left()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_snap_right":
                msg = self.windows.snap_right()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "window_center":
                msg = self.windows.center_window()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "show_desktop":
                msg = self.windows.show_desktop()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "switch_window":
                self.platform.send_hotkey(*KeyMap.switch_window())
                msg = "Switching app." if sys.platform == "darwin" else "Switching window."
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "switch_same_app_window":
                self.platform.send_hotkey(*KeyMap.switch_same_app_window())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Switching window.")

            elif act_type == "task_view":
                self.platform.send_hotkey(*KeyMap.task_view())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Showing all windows.")

            elif act_type == "window_full_screen":
                self.platform.send_hotkey(*KeyMap.full_screen())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Toggling full screen.")

            elif act_type == "next_desktop":
                self.platform.send_hotkey(*KeyMap.next_desktop())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Switching desktop.")

            elif act_type == "prev_desktop":
                self.platform.send_hotkey(*KeyMap.prev_desktop())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Switching desktop.")

            # 3. Browser & Web
            elif act_type == "web_search":
                msg = self.browser.search_web(action.query, engine=action.scope)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "open_url":
                msg = self.browser.open_url(action.url)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "browser_new_tab":
                ok, msg = self.browser.open_new_tab(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_switch_tab_number":
                tab_num = action.amount or action.line_number or 1
                ok, msg = self.browser.switch_to_tab_number(tab_num, preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_show_history":
                ok, msg = self.browser.show_history(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_show_downloads":
                ok, msg = self.browser.show_downloads(preferred_browser=action.app)
                if not ok and msg == "NOT_DISPLAYED":
                    # Fallback: open the system Downloads folder via the platform adapter
                    downloads_path = self.platform.get_standard_folders().get("Downloads")
                    if downloads_path and downloads_path.exists():
                        try:
                            folder_msg = self.platform.open_folder(downloads_path)
                            return ActionResult(action_id=action.id, action_type="open_folder", success=True, message=folder_msg)
                        except Exception:
                            pass
                    return ActionResult(action_id=action.id, action_type=act_type, success=False, message="No browser is open and could not locate the Downloads folder.")
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)


            elif act_type == "browser_close_tab":
                ok, msg = self.browser.close_tab(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_next_tab":
                ok, msg = self.browser.next_tab(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_prev_tab":
                ok, msg = self.browser.previous_tab(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_reopen_tab":
                ok, msg = self.browser.reopen_tab(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_reload":
                ok, msg = self.browser.reload(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type in ("browser_bookmark", "browser_bookmark_page"):
                ok, msg = self.browser.bookmark_page(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message="Bookmarked." if ok else msg)

            elif act_type == "browser_bookmarks_list":
                self.platform.send_hotkey(*KeyMap.bookmarks_list())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opening bookmarks.")

            elif act_type == "browser_address_bar":
                self.platform.send_hotkey(*KeyMap.address_bar())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Address bar ready.")

            elif act_type == "browser_find_in_page":
                self.platform.send_hotkey(*KeyMap.find_in_page())
                if action.text:
                    import time
                    time.sleep(0.1)
                    self.platform.type_text(action.text)
                    self.platform.send_key("enter")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Searching the page.")

            elif act_type == "browser_clear_data":
                self.platform.send_hotkey(*KeyMap.clear_browsing_data())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opened. Please confirm.")

            elif act_type == "browser_task_manager":
                self.platform.send_hotkey(*KeyMap.browser_task_manager())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opening Chrome's task manager.")

            elif act_type == "browser_go_back":
                self.platform.send_hotkey(*KeyMap.go_back())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Going back.")

            elif act_type == "browser_go_forward":
                self.platform.send_hotkey(*KeyMap.go_forward())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Going forward.")

            elif act_type == "browser_last_tab":
                self.platform.send_hotkey(*KeyMap.last_tab())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Last tab.")

            elif act_type == "browser_new_window":
                self.platform.send_hotkey(*KeyMap.new_window())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="New window.")

            elif act_type == "browser_zoom_in":
                ok, msg = self.browser.zoom_in(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_zoom_out":
                ok, msg = self.browser.zoom_out(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "browser_zoom_reset":
                ok, msg = self.browser.zoom_reset(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type in ("browser_incognito", "browser_open_incognito"):
                ok, msg = self.browser.new_incognito_window(preferred_browser=action.app)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            # 4. System & Clipboard
            elif act_type == "screenshot":
                path, msg = self.platform.capture_screenshot()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg, data={"path": str(path)})

            elif act_type in ("screen_read", "screen_read_all"):
                from app.vision.screen_interaction import screen_interaction
                user_prompt = action.query or action.text or "Describe what is displayed across the whole screen."
                summary, elements = screen_interaction.read_whole_screen(prompt=user_prompt)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=summary,
                                    data={"elements_count": len(elements)})

            elif act_type == "screen_click":
                from app.vision.screen_interaction import screen_interaction
                target = action.text or action.query or ""
                click_type = getattr(action, "patch_action", "single") or "single"
                ok, msg = screen_interaction.click_element(target, click_type=click_type)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "screen_double_click":
                from app.vision.screen_interaction import screen_interaction
                target = action.text or action.query or ""
                ok, msg = screen_interaction.click_element(target, click_type="double")
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "screen_right_click":
                from app.vision.screen_interaction import screen_interaction
                target = action.text or action.query or ""
                ok, msg = screen_interaction.click_element(target, click_type="right")
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "screen_select":
                from app.vision.screen_interaction import screen_interaction
                target = action.text or action.query or ""
                ok, msg = screen_interaction.select_element(target)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "screen_open":
                from app.vision.screen_interaction import screen_interaction
                target = action.text or action.path or action.query or ""
                ok, msg = screen_interaction.open_displayed_item(target)
                return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

            elif act_type == "volume_up":
                msg = self.platform.volume_up()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "volume_down":
                msg = self.platform.volume_down()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "volume_mute":
                msg = self.platform.volume_mute_toggle()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "copy":
                self.input_adapter.copy()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Copied.")

            elif act_type == "paste":
                self.input_adapter.paste()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Pasted.")

            elif act_type == "clear_clipboard":
                msg = self.clipboard.clear()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "select_all":
                self.input_adapter.select_all()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Selected all.")

            elif act_type == "undo":
                # Try code-level undo first (reverts semantic patch or line-edit on the active file)
                try:
                    from app.editor.code_patch_engine import code_patch_engine
                    active_f = self.vscode.get_active_file()
                    ok, undo_msg = code_patch_engine.undo_last_patch(active_f)
                    if ok:
                        reverted = getattr(code_patch_engine, 'last_reverted_path', None) or active_f
                        if reverted:
                            self.vscode.open_file(reverted)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=undo_msg)
                except Exception:
                    pass
                # Fallback: system-level undo (Ctrl+Z in focused app)
                self.input_adapter.undo()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Undone.")

            elif act_type == "redo":
                if self.vscode.is_available():
                    self.vscode.redo()
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Redone.")
                self.input_adapter.redo()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Redone.")

            elif act_type == "save":
                if self.vscode.is_available():
                    self.vscode.save()
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Saved.")
                self.input_adapter.save()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Saved.")

            # 5. VS Code & Code Editing
            elif act_type == "vscode_jump_line":
                line_num = action.line_number or 1
                success = self.vscode.jump_to_line(line_num)
                return ActionResult(action_id=action.id, action_type=act_type, success=success, message=f"Jumped to line {line_num}.")

            elif act_type == "vscode_open_file":
                raw_target = (action.path or "").strip()
                clean_target = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', raw_target, flags=re.IGNORECASE).strip() or raw_target
                clean_target = re.sub(r'\s+(?:folder|directory|project|workspace|file)$', '', clean_target, flags=re.IGNORECASE).strip() or clean_target
                clean_target = clean_target.strip("'\" ")

                # 0. Check direct path / absolute path first
                target_p = None
                try:
                    direct = Path(clean_target)
                    if direct.is_absolute() and direct.exists():
                        target_p = direct
                except Exception:
                    pass

                # 0b. Path resolver / spoken path check
                if not target_p:
                    target_p = self._resolve_target_path(clean_target, context_base=context_base)

                # 1. Check workspace first
                if not target_p:
                    target_p = self.vscode.find_in_workspace(clean_target)

                # 2. Search fallback
                if not target_p or not target_p.exists():
                    found = self.search.find_first(clean_target)
                    if found and found.exists():
                        target_p = found


                if target_p and target_p.exists():
                    success = self.vscode.open_file(target_p)
                    item_type = "folder" if target_p.is_dir() else "file"
                    return ActionResult(action_id=action.id, action_type=act_type, success=success,
                                        message=f"Opened {item_type} '{target_p.name}' in VS Code.")
                else:
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message=f"I couldn't find '{clean_target}' in your VS Code workspace or files.")

            elif act_type == "vscode_open_folder":
                folder_p = self._resolve_target_path(action.path or ".") or Path(".")
                import subprocess
                try:
                    subprocess.Popen(["code", str(folder_p)], shell=(sys.platform == "win32"))
                except Exception:
                    self.platform.open_app("code")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opening the folder in VS Code.")

            elif act_type == "vscode_open_file_at_line":
                p = self._resolve_target_path(action.path)
                ln = action.line_number or 1
                if p and p.exists():
                    self.vscode.open_file(p, line_number=ln)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Opening {p.name} at line {ln}.")
                else:
                    import subprocess
                    try:
                        subprocess.Popen(["code", "-g", f"{action.path}:{ln}"], shell=(sys.platform == "win32"))
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Opening {action.path} at line {ln}.")
                    except Exception:
                        return ActionResult(action_id=action.id, action_type=act_type, success=False, message=f"File '{action.path}' not found.")

            elif act_type == "vscode_diff":
                p_a = self._resolve_target_path(action.path) or action.path
                p_b = self._resolve_target_path(action.destination) or action.destination
                import subprocess
                try:
                    subprocess.Popen(["code", "-d", str(p_a), str(p_b)], shell=(sys.platform == "win32"))
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opening a diff.")
                except Exception as err:
                    return ActionResult(action_id=action.id, action_type=act_type, success=False, message=f"Could not open diff: {err}")

            elif act_type == "vscode_open_current_window":
                p = self._resolve_target_path(action.path) if action.path else None
                import subprocess
                args = ["code", "-r"] + ([str(p)] if p else [])
                subprocess.Popen(args, shell=(sys.platform == "win32"))
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opened.")

            elif act_type == "vscode_open_new_window":
                p = self._resolve_target_path(action.path) if action.path else None
                import subprocess
                args = ["code", "-n"] + ([str(p)] if p else [])
                subprocess.Popen(args, shell=(sys.platform == "win32"))
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="New window.")

            elif act_type == "vscode_quick_open":
                self.platform.send_hotkey(*KeyMap.vscode_quick_open())
                if action.path:
                    import time
                    time.sleep(0.1)
                    self.platform.type_text(action.path)
                    self.platform.send_key("enter")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=f"Opening {action.path or 'file'}.")

            elif act_type == "vscode_command_palette":
                self.platform.send_hotkey(*KeyMap.vscode_command_palette())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Command palette.")

            elif act_type == "vscode_terminal":
                self.platform.send_hotkey(*KeyMap.vscode_terminal())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Terminal open.")

            elif act_type == "vscode_toggle_sidebar":
                self.platform.send_hotkey(*KeyMap.vscode_toggle_sidebar())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Sidebar toggled.")

            elif act_type == "vscode_settings":
                self.platform.send_hotkey(*KeyMap.vscode_settings())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Opening settings.")

            elif act_type == "vscode_goto_symbol":
                self.platform.send_hotkey(*KeyMap.vscode_goto_symbol())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Go to symbol.")


            elif act_type == "vscode_goto_definition":
                ok = self.vscode.go_to_definition()
                if not ok:
                    self.platform.send_hotkey(*KeyMap.vscode_goto_definition())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Going to definition.")

            elif act_type == "vscode_format":
                ok = self.vscode.format_document()
                if not ok:
                    self.platform.send_hotkey(*KeyMap.vscode_format())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Formatted.")

            elif act_type == "vscode_save_all":
                if sys.platform == "darwin":
                    self.platform.send_hotkey("command", "option", "s")
                else:
                    self.platform.send_hotkey("ctrl", "k")
                    self.platform.send_key("s")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Saved.")

            elif act_type == "vscode_search_project":
                self.platform.send_hotkey(*KeyMap.vscode_search_project())
                if action.text:
                    import time
                    time.sleep(0.1)
                    self.platform.type_text(action.text)
                    self.platform.send_key("enter")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Searching the project.")

            elif act_type == "vscode_find_todo":
                self.platform.send_hotkey(*KeyMap.find_in_page())
                import time
                time.sleep(0.1)
                self.platform.type_text("TODO")
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Find open.")

            elif act_type == "vscode_replace_all":
                self.platform.send_hotkey(*KeyMap.vscode_replace_all())
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Find open.")

            elif act_type == "undo_last_edit":
                from app.editor.code_patch_engine import code_patch_engine
                active_f = self.vscode.get_active_file()
                ok, undo_msg = code_patch_engine.undo_last_patch(active_f)
                if ok:
                    reverted = getattr(code_patch_engine, 'last_reverted_path', None) or active_f
                    if reverted:
                        self.vscode.open_file(reverted)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Restored the previous version.")
                self.input_adapter.undo()
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Undone.")

            elif act_type == "vscode_next_file":
                success = self.vscode.next_file()
                active = self.vscode.get_active_file()
                name = active.name if active else "next file"
                return ActionResult(action_id=action.id, action_type=act_type, success=success, message=f"Switched to {name} in VS Code.")

            elif act_type == "vscode_prev_file":
                success = self.vscode.previous_file()
                active = self.vscode.get_active_file()
                name = active.name if active else "previous file"
                return ActionResult(action_id=action.id, action_type=act_type, success=success, message=f"Switched to {name} in VS Code.")

            elif act_type == "vscode_close_file":
                msg = self.vscode.close_file(action.path)
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "vscode_run_code":
                success = self.vscode.run_code()
                return ActionResult(action_id=action.id, action_type=act_type, success=success, message="Started execution.")

            elif act_type == "vscode_undo":
                success = self.vscode.undo()
                from app.editor.code_patch_engine import code_patch_engine as _cpe
                reverted_f = getattr(_cpe, 'last_reverted_path', None)
                msg = (f"Reverted code change in {reverted_f.name}." if reverted_f
                       else "Reverted code edit.")
                return ActionResult(action_id=action.id, action_type=act_type, success=success, message=msg)

            elif act_type == "vscode_read_line":
                line_num = action.line_number or 1
                if action.path:
                    p = self._resolve_target_path(action.path)
                    if p and p.is_file():
                        self.vscode.open_file(p, line_number=line_num)
                    else:
                        self.vscode.jump_to_line(line_num)
                else:
                    self.vscode.jump_to_line(line_num)


                content = self.vscode.read_document()
                if content:
                    lines = content.splitlines()
                    idx = line_num - 1
                    if 0 <= idx < len(lines):
                        line_text = lines[idx].strip()
                        msg = f"Line {line_num} says: {line_text}" if line_text else f"Line {line_num} is empty."
                    else:
                        msg = f"Line {line_num} does not exist in this file."
                else:
                    msg = f"Showing line {line_num} in VS Code."
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "vscode_edit":
                # Resolve active file
                active_file = self.vscode.get_active_file()
                if not active_file or not active_file.is_file():
                    active_file = context_base if context_base and context_base.is_file() else None
                if not active_file:
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="No active code file detected. Please open a file in VS Code first.")

                token = (action.text or action.instruction or "").strip()

                # ------ A. REPLACE_IN_LINE:{line}:{old}::{new} ------
                if token.startswith("REPLACE_IN_LINE:"):
                    # format: REPLACE_IN_LINE:<line>:<old>::<new>
                    rest = token[len("REPLACE_IN_LINE:"):]
                    parts = rest.split("::", 1)
                    if len(parts) == 2:
                        header, new_val = parts
                        header_parts = header.split(":", 1)
                        if len(header_parts) == 2:
                            ln, old_val = int(header_parts[0]), header_parts[1]
                            result_msg = self._file_replace_in_line(active_file, ln, old_val, new_val)
                            self.vscode.open_file(active_file)
                            return ActionResult(action_id=action.id, action_type=act_type, success=True, message=result_msg)
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="Could not parse the replace instruction.")

                # ------ B. REPLACE_LINE:{line}::{new_text} ------
                elif token.startswith("REPLACE_LINE:"):
                    rest = token[len("REPLACE_LINE:"):]
                    parts = rest.split("::", 1)
                    if len(parts) == 2:
                        ln, new_text = int(parts[0]), parts[1]
                        ok = self.vscode.apply_edit(active_file, ln, ln, new_text)
                        self.vscode.open_file(active_file)
                        msg = f"Line {ln} replaced." if ok else f"Could not replace line {ln}."
                        return ActionResult(action_id=action.id, action_type=act_type, success=ok, message=msg)

                # ------ C. DELETE_LINE:{line} ------
                elif token.startswith("DELETE_LINE:") and not token.startswith("DELETE_LINES:"):
                    ln = int(token[len("DELETE_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self._file_delete_lines(active_file, ln, ln)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message=f"Line {ln} deleted." if ok else f"Could not delete line {ln}.")

                # ------ D. DELETE_LINES:{start}:{end} ------
                elif token.startswith("DELETE_LINES:"):
                    parts = token[len("DELETE_LINES:"):].split(":")
                    if len(parts) == 2:
                        s, e = int(parts[0]), int(parts[1])
                        ok = self._file_delete_lines(active_file, s, e)
                        self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                            message=f"Lines {s} to {e} deleted." if ok else "Could not delete lines.")

                # ------ E. INSERT_AFTER:{line}::{text} ------
                elif token.startswith("INSERT_AFTER:"):
                    rest = token[len("INSERT_AFTER:"):]
                    parts = rest.split("::", 1)
                    if len(parts) == 2:
                        ln, new_text = int(parts[0]), parts[1]
                        if ln == 0:
                            ln = self.vscode.get_cursor_line()
                        ok = self._file_insert_line(active_file, ln, new_text, after=True)
                        self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                            message=f"Inserted after line {ln}." if ok else "Insert failed.")

                # ------ F. INSERT_BEFORE:{line}::{text} ------
                elif token.startswith("INSERT_BEFORE:"):
                    rest = token[len("INSERT_BEFORE:"):]
                    parts = rest.split("::", 1)
                    if len(parts) == 2:
                        ln, new_text = int(parts[0]), parts[1]
                        if ln == 0:
                            ln = self.vscode.get_cursor_line()
                        ok = self._file_insert_line(active_file, ln, new_text, after=False)
                        self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                            message=f"Inserted before line {ln}." if ok else "Insert failed.")

                # ------ G. COMMENT_LINE:{line} ------
                elif token.startswith("COMMENT_LINE:"):
                    ln = int(token[len("COMMENT_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self.vscode.toggle_comment(ln)
                    if not ok:
                        ok = self._file_toggle_comment(active_file, ln, add_comment=True)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message=f"Line {ln} commented out." if ok else "Could not comment line.")

                # ------ H. UNCOMMENT_LINE:{line} ------
                elif token.startswith("UNCOMMENT_LINE:"):
                    ln = int(token[len("UNCOMMENT_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self.vscode.toggle_comment(ln)
                    if not ok:
                        ok = self._file_toggle_comment(active_file, ln, add_comment=False)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message=f"Line {ln} uncommented." if ok else "Could not comment line.")

                # ------ I. RENAME_FUNC:{old}:{new} ------
                elif token.startswith("RENAME_FUNC:"):
                    parts = token.split(":")
                    if len(parts) >= 3:
                        proposal = self.code_engine.propose_function_rename(active_file, parts[1], parts[2])
                        if proposal:
                            self.code_engine.apply_proposal(proposal)
                            self.vscode.open_file(active_file)
                            return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                                message=proposal.explanation)
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="Could not parse the rename instruction.")

                # ------ J. ADD_TRY_EXCEPT:{line} ------
                elif token.startswith("ADD_TRY_EXCEPT"):
                    parts = token.split(":")
                    ln = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else (action.line_number or 0)
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    proposal = self.code_engine.propose_exception_handling_at_line(active_file, ln)
                    if proposal:
                        self.code_engine.apply_proposal(proposal)
                        self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                            message=proposal.explanation)
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="Could not generate the error-handling block.")

                # ------ K. APPEND_TO_LINE:{line}::{text} ------
                elif token.startswith("APPEND_TO_LINE:"):
                    rest = token[len("APPEND_TO_LINE:"):]
                    parts = rest.split("::", 1)
                    if len(parts) == 2:
                        ln, append_text = int(parts[0]), parts[1]
                        if ln == 0:
                            ln = self.vscode.get_cursor_line()
                        ok = self._file_append_to_line(active_file, ln, append_text)
                        self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                            message="Added." if ok else f"Could not append to line {ln}.")

                # ------ L. DUPLICATE_LINE:{line} ------
                elif token.startswith("DUPLICATE_LINE:"):
                    ln = int(token[len("DUPLICATE_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self.vscode.duplicate_line(ln)
                    if not ok:
                        ok = self._file_duplicate_line(active_file, ln)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message="Line duplicated." if ok else "Could not duplicate line.")

                # ------ M. MOVE_LINE_UP:{line} / MOVE_LINE_DOWN:{line} ------
                elif token.startswith("MOVE_LINE_UP:"):
                    ln = int(token[len("MOVE_LINE_UP:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self.vscode.move_line_up() if hasattr(self.vscode, "move_line_up") else False
                    if not ok:
                        ok = self._file_move_line(active_file, ln, up=True)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message="Line moved." if ok else "Could not move line.")

                elif token.startswith("MOVE_LINE_DOWN:"):
                    ln = int(token[len("MOVE_LINE_DOWN:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self.vscode.move_line_down() if hasattr(self.vscode, "move_line_down") else False
                    if not ok:
                        ok = self._file_move_line(active_file, ln, up=False)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message="Line moved." if ok else "Could not move line.")

                # ------ N. INDENT_LINE:{line} / OUTDENT_LINE:{line} ------
                elif token.startswith("INDENT_LINE:"):
                    ln = int(token[len("INDENT_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self._file_indent_line(active_file, ln, indent=True)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message="Indented." if ok else "Could not indent line.")

                elif token.startswith("OUTDENT_LINE:"):
                    ln = int(token[len("OUTDENT_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self._file_indent_line(active_file, ln, indent=False)
                    self.vscode.open_file(active_file)
                    return ActionResult(action_id=action.id, action_type=act_type, success=ok,
                                        message="Outdented." if ok else "Could not outdent line.")

                # ------ O. SELECT_LINE:{line} ------
                elif token.startswith("SELECT_LINE:"):
                    ln = int(token[len("SELECT_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    ok = self.vscode.select_line(ln)
                    if not ok:
                        self.vscode.jump_to_line(ln)
                        self.platform.send_hotkey(*KeyMap.vscode_select_line())
                    return ActionResult(action_id=action.id, action_type=act_type, success=True,
                                        message=f"Line {ln} selected.")

                # ------ P. COPY_LINE:{line} ------
                elif token.startswith("COPY_LINE:"):
                    ln = int(token[len("COPY_LINE:"):])
                    if ln == 0:
                        ln = self.vscode.get_cursor_line()
                    lines, _ = self._read_lines(active_file)
                    idx = ln - 1
                    if 0 <= idx < len(lines):
                        self.platform.set_clipboard_text(lines[idx].rstrip("\r\n"))
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Copied.")

                # ------ Q. RENAME_VAR:{old}:{new} ------
                elif token.startswith("RENAME_VAR:"):
                    parts = token.split(":")
                    if len(parts) >= 3:
                        old_v, new_v = parts[1], parts[2]
                        lines, _ = self._read_lines(active_file)
                        new_lines = [re.sub(r'\b' + re.escape(old_v) + r'\b', new_v, line) for line in lines]
                        self._write_lines(active_file, new_lines)
                        self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Renamed.")

                # ------ R. FORMAT_FILE ------
                elif token == "FORMAT_FILE":
                    ok = self.vscode.format_document()
                    if not ok:
                        self.platform.send_hotkey(*KeyMap.vscode_format())
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Formatted.")

                # ------ S. FIND_IN_FILE:{query} ------
                elif token.startswith("FIND_IN_FILE:"):
                    q = token[len("FIND_IN_FILE:"):]
                    self.platform.send_hotkey(*KeyMap.find_in_page())
                    if q:
                        import time
                        time.sleep(0.1)
                        self.platform.type_text(q)
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Find open.")

                # ------ T. REPLACE_ALL ------
                elif token == "REPLACE_ALL":
                    self.platform.send_hotkey(*KeyMap.vscode_replace_all())
                    return ActionResult(action_id=action.id, action_type=act_type, success=True, message="Find open.")

                # ------ U. Free-text instruction → targeted patch via code_patch_engine ------
                elif token:
                    from app.editor.code_patch_engine import code_patch_engine, TargetedPatch
                    current_code = self.vscode.read_document(active_file)
                    if not current_code:
                        return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                            message="Could not read the active file.")
                    # Build a vscode_patch action from the free-text instruction via AI
                    from app.ai.factory import AIProviderFactory
                    from app.core.models import ScreenContext
                    lines = current_code.splitlines()
                    snippet = "\n".join(f"{i+1}: {l}" for i, l in enumerate(lines[:100]))
                    mini_prompt = (
                        f"You are a code editor. Return a vscode_patch JSON action only.\n"
                        f"Instruction: {token}\n"
                        f"File: {active_file.name}\n"
                        f"Content (first 100 lines):\n{snippet}\n\n"
                        f"Return JSON: {{\"target_code\": \"exact snippet\", \"replacement_code\": \"new snippet\", "
                        f"\"patch_action\": \"replace\", \"explanation\": \"what changed\"}}"
                    )
                    provider = AIProviderFactory.get_provider()
                    ctx = ScreenContext()
                    ctx.vscode_file = str(active_file)
                    mini_plan = provider.plan(mini_prompt, ctx)
                    import json as _json
                    raw = mini_plan.reply.strip()
                    raw = re.sub(r'^```[^\n]*\n?', '', raw)
                    raw = re.sub(r'\n?```$', '', raw).strip()
                    patch_data = {}
                    try:
                        patch_data = _json.loads(raw)
                    except Exception:
                        # Fall back: if AI returns whole file, wrap in patch
                        if len(raw) > 20 and not raw.startswith("{"):
                            patch_data = {
                                "target_code": lines[0] if lines else "",
                                "replacement_code": raw,
                                "patch_action": "replace",
                                "explanation": f"Applied: {token}",
                            }

                    if patch_data.get("target_code") and patch_data.get("replacement_code"):
                        tp = TargetedPatch(
                            file_path=active_file,
                            target_code=patch_data["target_code"],
                            replacement_code=patch_data["replacement_code"],
                            explanation=patch_data.get("explanation", f"Applied: {token}"),
                            patch_action=patch_data.get("patch_action", "replace"),
                        )
                        success, msg, diff = code_patch_engine.apply_patch(tp)
                        if success:
                            self.vscode.open_file(active_file)
                        return ActionResult(action_id=action.id, action_type=act_type, success=success, message=msg)
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="Could not determine what to change. Try being more specific.")

                return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                    message="No edit instruction provided.")

            # ------ vscode_patch: targeted semantic patch (preferred code edit path) ------
            elif act_type == "vscode_patch":
                from app.editor.code_patch_engine import code_patch_engine, TargetedPatch
                from pathlib import Path

                target_file: Optional[Path] = None
                if action.path:
                    target_file = self._resolve_target_path(action.path)
                else:
                    target_file = self.vscode.get_active_file()

                    if not target_file or not target_file.is_file():
                        target_file = context_base if context_base and context_base.is_file() else None

                if not target_file or not target_file.is_file():
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="No active file found. Please open a file in VS Code first.")

                target_code = getattr(action, 'target_code', None) or ""
                replacement_code = getattr(action, 'replacement_code', None) or ""
                if not target_code and not replacement_code:
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="Patch requires target_code and replacement_code.")

                tp = TargetedPatch(
                    file_path=target_file,
                    target_code=target_code,
                    replacement_code=replacement_code,
                    explanation=getattr(action, 'instruction', None) or f"Patched {target_file.name}",
                    line_hint=action.line_number,
                    symbol_name=getattr(action, 'symbol', None),
                    patch_action=getattr(action, 'patch_action', 'replace') or 'replace',
                )
                success, msg, diff = code_patch_engine.apply_patch(tp)
                if success:
                    self.vscode.open_file(target_file)
                return ActionResult(action_id=action.id, action_type=act_type, success=success, message=msg)

            # ------ vscode_inspect: explain active file or selection ------
            elif act_type == "vscode_inspect":
                active_file = self.vscode.get_active_file()
                if not active_file or not active_file.is_file():
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="No active file found in VS Code.")
                ctx_info = self.code_engine.inspect_active_context(active_file, line_hint=None)
                if ctx_info:
                    msg = f"In {active_file.name}: {ctx_info}"
                else:
                    msg = f"Opened {active_file.name}. Unable to extract context automatically."
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            # ------ vscode_outline: speak file structure ------
            elif act_type == "vscode_outline":
                active_file = self.vscode.get_active_file()
                if not active_file or not active_file.is_file():
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="No active file found in VS Code.")
                outline = self.code_engine.extract_file_outline(active_file)
                if outline:
                    parts = [f"{s['kind']} {s['name']} at line {s['line']}" for s in outline[:8]]
                    msg = f"{active_file.name} contains: " + ", ".join(parts)
                else:
                    msg = f"Could not extract outline from {active_file.name}."
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            # ------ vscode_find_symbols: search workspace for a symbol ------
            elif act_type == "vscode_find_symbols":
                query = action.query or getattr(action, 'text', None) or ""
                if not query:
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="Please specify what symbol or function to find.")
                scope_dir = None
                if action.scope:
                    from pathlib import Path
                    scope_dir = Path(action.scope) if Path(action.scope).is_dir() else None
                if not scope_dir and context_base:
                    scope_dir = context_base if context_base.is_dir() else context_base.parent
                if not scope_dir:
                    return ActionResult(action_id=action.id, action_type=act_type, success=False,
                                        message="No workspace directory found. Open a folder in VS Code first.")
                results = self.code_engine.find_symbols_in_workspace(query, scope_dir)
                if results:
                    parts = [f"{r['symbol']} in {r['file']} at line {r['line']}" for r in results[:5]]
                    msg = "Found: " + "; ".join(parts)
                else:
                    msg = f"No results for '{query}' in the workspace."
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=msg)

            elif act_type == "answer_question":
                reply_text = action.text or action.query or ""
                return ActionResult(action_id=action.id, action_type=act_type, success=True, message=reply_text)

            else:
                return ActionResult(action_id=action.id, action_type=act_type, success=False, message=f"Unknown action type: {act_type}")

        except Exception as e:
            logger.error(f"Action execution error ({act_type}): {e}")
            spoken_msg = friendly_errors.translate(e, action)
            return ActionResult(action_id=action.id, action_type=act_type, success=False, message=spoken_msg, error=str(e))

    # ------------------------------------------------------------------
    # Private file-manipulation helpers (no IPC required — operate on disk)
    # All create a .bak backup before writing.
    # ------------------------------------------------------------------

    @staticmethod
    def _read_lines(path: Path):
        """
        Read a file and return (lines_with_endings, detected_eol).
        Always reads as bytes first to avoid Python's newline translation,
        then decodes as UTF-8 (with cp1252 fallback).
        splitlines(keepends=True) correctly handles \r\n, \n, and \r.
        """
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        # Detect the dominant EOL style in this file
        crlf_count = text.count("\r\n")
        lf_count   = text.count("\n") - crlf_count
        eol = "\r\n" if crlf_count >= lf_count else "\n"
        return text.splitlines(keepends=True), eol

    @staticmethod
    def _write_lines(path: Path, lines):
        """
        Write lines back to disk using raw bytes — bypasses Python's text-mode
        \n→\r\n translation on Windows, which would double every \r\n ending.

        Also records the pre-write state in code_patch_engine's undo stack so
        voice commands like 'undo', 'undo change', 'revert edit' can restore
        the file even when the change was made via a REPLACE_IN_LINE / DELETE_LINE
        / INSERT token (not a full vscode_patch action).
        """
        import shutil as _sh
        bak = path.with_suffix(path.suffix + ".bak")
        # Capture original content for undo stack BEFORE overwriting
        try:
            from app.editor.code_patch_engine import code_patch_engine as _cpe
            _orig_raw = path.read_bytes()
            try:
                _orig_text = _orig_raw.decode("utf-8")
            except UnicodeDecodeError:
                _orig_text = _orig_raw.decode("cp1252", errors="replace")
            _crlf = _orig_text.count("\r\n")
            _lf = _orig_text.count("\n") - _crlf
            _orig_eol = "\r\n" if _crlf >= _lf else "\n"
            _cpe._undo_history.append({
                "path": path,
                "original_content": _orig_text,
                "modified_content": "".join(lines),
                "diff": "",
                "explanation": f"Line edit in {path.name}",
                "eol": _orig_eol,
            })
        except Exception:
            pass
        _sh.copy2(path, bak)
        # write_bytes preserves whatever endings are already in the lines
        path.write_bytes("".join(lines).encode("utf-8"))

    def _file_replace_in_line(self, path: Path, line_no: int, old: str, new: str) -> str:
        """
        Replace the first occurrence of `old` with `new` on 1-indexed line `line_no`.
        The match is done against the stripped line content so leading/trailing
        whitespace and EOL chars don't affect the search.
        Returns a spoken result message.
        """
        lines, _ = self._read_lines(path)
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            return f"Line {line_no} does not exist in this file (file has {len(lines)} lines)."

        original = lines[idx]
        # Strip only the EOL chars for matching, keep indent intact
        eol = ""
        stripped = original
        for ending in ("\r\n", "\n", "\r"):
            if original.endswith(ending):
                eol = ending
                stripped = original[: -len(ending)]
                break

        # If user intended to replace the whole content of the line
        if old.lower().strip() in ("content", "the content", "code", "the code", "text", "the text", "everything", "whole line", "entire line"):
            self.vscode.apply_edit(path, line_no, line_no, new)
            return f"Done. Replaced line {line_no} with: {new}"

        target_old = old
        if target_old not in stripped:
            # Try without quotes if user or STT added quotes
            unquoted = target_old.strip("'\"")
            if unquoted and unquoted in stripped:
                target_old = unquoted
            elif target_old.lower() in stripped.lower():
                # Case-insensitive substring match
                ci_idx = stripped.lower().find(target_old.lower())
                target_old = stripped[ci_idx:ci_idx + len(target_old)]
            elif unquoted and unquoted.lower() in stripped.lower():
                ci_idx = stripped.lower().find(unquoted.lower())
                target_old = stripped[ci_idx:ci_idx + len(unquoted)]
            else:
                return f"I could not find '{old}' on line {line_no}. Line contains: {stripped.strip()!r}"

        replaced = stripped.replace(target_old, new, 1)
        if self.vscode.is_available():
            ok = self.vscode.apply_edit(path, line_no, line_no, replaced)
            if ok:
                logger.info(f"Replaced '{target_old}' → '{new}' on line {line_no} of {path.name} via IPC")
                return f"Done. Replaced '{target_old}' with '{new}' on line {line_no}."
        lines[idx] = replaced + eol
        self._write_lines(path, lines)
        logger.info(f"Replaced '{target_old}' → '{new}' on line {line_no} of {path.name}")
        return f"Done. Replaced '{target_old}' with '{new}' on line {line_no}."

    def _file_delete_lines(self, path: Path, start: int, end: int) -> bool:
        """Delete 1-indexed lines start..end inclusive. Returns True on success."""
        if self.vscode.is_available():
            ok = self.vscode.delete_lines(start, end)
            if ok:
                logger.info(f"Deleted lines {start}-{end} from {path.name} via IPC")
                return True
        try:
            lines, _ = self._read_lines(path)
            idx_s = max(0, start - 1)
            idx_e = min(len(lines), end)   # slice end is exclusive so `end` not `end-1`
            if idx_s >= len(lines):
                return False
            del lines[idx_s:idx_e]
            self._write_lines(path, lines)
            logger.info(f"Deleted lines {start}-{end} from {path.name}")
            return True
        except Exception as e:
            logger.error(f"_file_delete_lines failed: {e}")
            return False

    def _file_insert_line(self, path: Path, line_no: int, text: str, after: bool) -> bool:
        """
        Insert `text` as a new line after or before 1-indexed line `line_no`.
        Uses the file's native EOL style so the inserted line doesn't corrupt endings.
        Preserves the indentation of the reference line.
        """
        if self.vscode.is_available():
            target_line = (line_no + 1) if after else line_no
            ok = self.vscode.insert_line(target_line, text)
            if ok:
                logger.info(f"Inserted line {target_line} into {path.name} via IPC")
                return True
        try:
            lines, eol = self._read_lines(path)
            idx = line_no - 1
            if idx < 0 or idx > len(lines):
                return False
            ref_line = lines[idx] if idx < len(lines) else ""
            # Count leading whitespace chars (don't count \r or \n)
            indent = len(ref_line) - len(ref_line.lstrip(" \t"))
            new_line = " " * indent + text.strip() + eol
            insert_at = idx + 1 if after else idx
            lines.insert(insert_at, new_line)
            self._write_lines(path, lines)
            logger.info(f"Inserted line {'after' if after else 'before'} {line_no} in {path.name}")
            return True
        except Exception as e:
            logger.error(f"_file_insert_line failed: {e}")
            return False

    def _file_toggle_comment(self, path: Path, line_no: int, add_comment: bool) -> bool:
        """Add or remove a leading comment character on 1-indexed line `line_no`."""
        try:
            lines, eol = self._read_lines(path)
            idx = line_no - 1
            if idx < 0 or idx >= len(lines):
                return False

            original = lines[idx]
            # Separate trailing EOL from content
            line_eol = ""
            content_raw = original
            for ending in ("\r\n", "\n", "\r"):
                if original.endswith(ending):
                    line_eol = ending
                    content_raw = original[: -len(ending)]
                    break

            stripped = content_raw.lstrip()
            indent = content_raw[: len(content_raw) - len(stripped)]

            # Detect comment style from file extension
            suffix = path.suffix.lower()
            if suffix in (".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
                          ".cs", ".go", ".swift", ".rs", ".kt"):
                char = "//"
            elif suffix in (".html", ".xml"):
                return False   # too complex for a simple toggle
            else:
                char = "#"     # Python, shell, YAML, Ruby, TOML, etc.

            if add_comment:
                if not stripped.startswith(char):
                    lines[idx] = f"{indent}{char} {stripped}{line_eol}"
            else:
                if stripped.startswith(char + " "):
                    lines[idx] = f"{indent}{stripped[len(char)+1:]}{line_eol}"
                elif stripped.startswith(char):
                    lines[idx] = f"{indent}{stripped[len(char):]}{line_eol}"

            self._write_lines(path, lines)
            logger.info(f"{'Commented' if add_comment else 'Uncommented'} line {line_no} in {path.name}")
            return True
        except Exception as e:
            logger.error(f"_file_toggle_comment failed: {e}")
            return False

    def _file_append_to_line(self, path: Path, line_no: int, text: str) -> bool:
        """Append text to the end of 1-indexed line line_no before the EOL."""
        try:
            lines, _ = self._read_lines(path)
            idx = line_no - 1
            if idx < 0 or idx >= len(lines):
                return False
            orig = lines[idx]
            eol = ""
            stripped = orig
            for ending in ("\r\n", "\n", "\r"):
                if orig.endswith(ending):
                    eol = ending
                    stripped = orig[:-len(ending)]
                    break
            lines[idx] = stripped + text + eol
            self._write_lines(path, lines)
            return True
        except Exception as e:
            logger.error(f"_file_append_to_line failed: {e}")
            return False

    def _file_duplicate_line(self, path: Path, line_no: int) -> bool:
        """Duplicate 1-indexed line line_no (inserting a copy right below it)."""
        try:
            lines, _ = self._read_lines(path)
            idx = line_no - 1
            if idx < 0 or idx >= len(lines):
                return False
            lines.insert(idx + 1, lines[idx])
            self._write_lines(path, lines)
            return True
        except Exception as e:
            logger.error(f"_file_duplicate_line failed: {e}")
            return False

    def _file_move_line(self, path: Path, line_no: int, up: bool) -> bool:
        """Move 1-indexed line line_no up or down by swapping with adjacent line."""
        try:
            lines, _ = self._read_lines(path)
            idx = line_no - 1
            target_idx = idx - 1 if up else idx + 1
            if idx < 0 or idx >= len(lines) or target_idx < 0 or target_idx >= len(lines):
                return False
            lines[idx], lines[target_idx] = lines[target_idx], lines[idx]
            self._write_lines(path, lines)
            return True
        except Exception as e:
            logger.error(f"_file_move_line failed: {e}")
            return False

    def _file_indent_line(self, path: Path, line_no: int, indent: bool) -> bool:
        """Add or remove 4 spaces at the start of 1-indexed line line_no."""
        try:
            lines, _ = self._read_lines(path)
            idx = line_no - 1
            if idx < 0 or idx >= len(lines):
                return False
            orig = lines[idx]
            if indent:
                lines[idx] = "    " + orig
            else:
                if orig.startswith("    "):
                    lines[idx] = orig[4:]
                elif orig.startswith("\t"):
                    lines[idx] = orig[1:]
                else:
                    lines[idx] = orig.lstrip(" ")
            self._write_lines(path, lines)
            return True
        except Exception as e:
            logger.error(f"_file_indent_line failed: {e}")
            return False

