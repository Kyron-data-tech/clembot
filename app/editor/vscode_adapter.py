"""
app/editor/vscode_adapter.py

VS Code integration with 3-layer file detection:
  1. IPC extension (live cursor + full path) — best
  2. VS Code globalStorage/storage.json workspace + window title filename — no extension needed
  3. Last-known path cache — per-session fallback

All edit operations work directly on disk, so no extension is required.
"""

import ctypes
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import unquote, urlparse

import httpx

from app.editor.base import EditorAdapter
from app.ipc.server import ipc_server
from app.logging.logger import logger

_IPC_BASE = "http://127.0.0.1:25362"


# ---------------------------------------------------------------------------
# IPC helper
# ---------------------------------------------------------------------------

def _ipc_post(path: str, payload: Dict[str, Any], timeout: float = 4.0) -> Dict[str, Any]:
    """Synchronous HTTP POST to the IPC server (avoids asyncio cross-thread deadlock)."""
    try:
        resp = httpx.post(f"{_IPC_BASE}{path}", json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug(f"IPC HTTP call to {path} failed: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# VS Code state readers
# ---------------------------------------------------------------------------

def _get_vscode_user_data_dirs() -> List[Path]:
    """
    Returns existing user data paths where VS Code User configuration/storage lives
    across macOS, Windows, and Linux.
    """
    base_roots: List[Path] = []
    if sys.platform == "darwin":
        mac_app_support = Path.home() / "Library" / "Application Support"
        if mac_app_support.is_dir():
            base_roots.append(mac_app_support)
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata and os.path.isdir(appdata):
            base_roots.append(Path(appdata))
    else:
        config_dir = Path.home() / ".config"
        if config_dir.is_dir():
            base_roots.append(config_dir)

    results: List[Path] = []
    for base in base_roots:
        for variant in ("Code", "Code - Insiders", "VSCodium"):
            cand = base / variant / "User"
            if cand.is_dir():
                results.append(cand)
    return results


def _get_vscode_workspace_from_storage() -> Optional[Path]:
    """
    Read VS Code's globalStorage/storage.json to find the current workspace folder.
    Returns the workspace Path or None.
    """
    for user_dir in _get_vscode_user_data_dirs():
        storage = user_dir / "globalStorage" / "storage.json"
        if not storage.is_file():
            continue
        try:
            data = json.loads(storage.read_text(encoding="utf-8", errors="replace"))
            ws_state = data.get("windowsState", {})
            last = ws_state.get("lastActiveWindow", {})
            folder_uri = last.get("folder") or last.get("workspace", {}).get("configPath")
            if folder_uri:
                p = _uri_to_path(folder_uri)
                if p and p.is_dir():
                    return p
            for win in ws_state.get("openedWindows", []):
                f_uri = win.get("folder") or win.get("workspace", {}).get("configPath")
                if f_uri:
                    p = _uri_to_path(f_uri)
                    if p and p.is_dir():
                        return p
        except Exception as e:
            logger.debug(f"Failed to parse VS Code storage.json at {storage}: {e}")

    return None


def _uri_to_path(uri: str) -> Optional[Path]:
    """Convert a VS Code file:// URI (possibly URL-encoded) to a Path."""
    try:
        parsed = urlparse(unquote(uri))
        if parsed.scheme == "file":
            p = parsed.path
            # Windows: /c:/Users/... → c:/Users/...
            if p.startswith("/") and len(p) > 2 and p[2] == ":":
                p = p[1:]
            return Path(p)
    except Exception:
        pass
    return None


def _get_vscode_window_titles() -> List[str]:
    """
    Enumerate all window titles belonging to a VS Code process.
    On macOS: uses AppleScript via System Events.
    On Windows: uses pure ctypes EnumWindows.
    """
    if sys.platform == "darwin":
        try:
            from app.platform_layer.macos.applescript import run_multiline_applescript
            script = '''
            tell application "System Events"
                set out to ""
                repeat with p in (every process whose name is "Code" or name is "Visual Studio Code")
                    try
                        repeat with w in windows of p
                            set out to out & (name of w) & "|||"
                        end repeat
                    end try
                end repeat
                return out
            end tell
            '''
            success, out = run_multiline_applescript(script, timeout=3.0)
            if success and out:
                return [t.strip() for t in out.split("|||") if t.strip()]
        except Exception as e:
            logger.debug(f"macOS VS Code window title query failed: {e}")
        return []

    if sys.platform == "win32" and hasattr(ctypes, "windll"):
        titles: List[str] = []
        try:
            import ctypes.wintypes as wt
            WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

            def _callback(hwnd: int, _: int) -> bool:
                try:
                    if not ctypes.windll.user32.IsWindowVisible(hwnd):
                        return True
                    buf = ctypes.create_unicode_buffer(512)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                    title = buf.value
                    if title and ("Visual Studio Code" in title or "Code" in title):
                        titles.append(title)
                except Exception:
                    pass
                return True

            ctypes.windll.user32.EnumWindows(WNDENUMPROC(_callback), 0)
            return titles
        except Exception as e:
            logger.debug(f"Windows EnumWindows error: {e}")
            return []

    return []



def _parse_filename_from_title(title: str) -> Optional[str]:
    """
    Parse the open filename from a VS Code window title.

    Formats handled:
      main.py — myproject — Visual Studio Code
      ● main.py — myproject — Visual Studio Code   (unsaved changes)
      myproject — Visual Studio Code               (no file open, folder only)
      Welcome — Visual Studio Code
    """
    # Strip unsaved indicator (● or •)
    title = re.sub(r"^[●•\u25cf\*]\s*", "", title).strip()

    if "Visual Studio Code" not in title:
        return None

    # Split on em-dash, en-dash, or " - "
    parts = re.split(r"\s*[—–]\s*|\s+-\s+", title)
    if not parts:
        return None

    candidate = parts[0].strip()

    # Must look like a filename (has a dot, not a generic word)
    if "." in candidate and candidate not in ("Visual Studio Code", "Welcome", "Untitled"):
        return candidate

    return None


def _resolve_from_vscdb() -> Optional[Path]:
    """
    Read active editor tab directly from VS Code's workspaceStorage/<id>/state.vscdb.
    Works reliably without the VS Code extension, without window title inspection,
    and without GUI automation.
    """
    ws_folder = _get_vscode_workspace_from_storage() or VSCodeAdapter._cached_workspace

    for user_dir in _get_vscode_user_data_dirs():
        ws_root = user_dir / "workspaceStorage"
        if not ws_root.is_dir():
            continue


        try:
            dirs = sorted(ws_root.glob("*"), key=lambda d: d.stat().st_mtime if d.is_dir() else 0, reverse=True)
        except Exception:
            dirs = list(ws_root.glob("*"))

        # If a workspace folder is known, check that matching directory first
        ordered_dirs: List[Path] = []
        if ws_folder:
            for d in dirs:
                ws_json = d / "workspace.json"
                if ws_json.is_file():
                    try:
                        wdata = json.loads(ws_json.read_text(encoding="utf-8", errors="replace"))
                        folder_uri = wdata.get("folder", "")
                        if folder_uri and str(_uri_to_path(folder_uri)).lower() == str(ws_folder).lower():
                            ordered_dirs.append(d)
                            break
                    except Exception:
                        pass
        for d in dirs:
            if d not in ordered_dirs:
                ordered_dirs.append(d)

        for d in ordered_dirs:
            db_path = d / "state.vscdb"
            if not db_path.is_file():
                continue
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
                cur = conn.cursor()

                # 1. Try memento/workbench.parts.editor (active tab in focused editor group)
                cur.execute("SELECT value FROM ItemTable WHERE key = 'memento/workbench.parts.editor'")
                row = cur.fetchone()
                if row:
                    val = json.loads(row[0])
                    grid = val.get("editorpart.state", {}).get("serializedGrid", {})
                    root = grid.get("root", {})
                    leaves: List[Dict[str, Any]] = []

                    def collect_leaves(node):
                        if not isinstance(node, dict):
                            return
                        if node.get("type") == "leaf":
                            leaves.append(node.get("data", {}))
                        elif node.get("type") == "branch":
                            for child in node.get("data", []):
                                collect_leaves(child)

                    collect_leaves(root)
                    for leaf in leaves:
                        editors = leaf.get("editors", [])
                        mru = leaf.get("mru", [])
                        if mru and editors:
                            active_idx = mru[0]
                            if 0 <= active_idx < len(editors):
                                ed_val = json.loads(editors[active_idx].get("value", "{}"))
                                fspath = ed_val.get("resourceJSON", {}).get("fsPath")
                                if fspath and Path(fspath).is_file():
                                    conn.close()
                                    logger.info(f"Resolved active VS Code file from state.vscdb: {fspath}")
                                    p = Path(fspath)
                                    VSCodeAdapter._cached_file = p
                                    ws_json = d / "workspace.json"
                                    if ws_json.is_file():
                                        try:
                                            wdata = json.loads(ws_json.read_text(encoding="utf-8", errors="replace"))
                                            w_uri = wdata.get("folder") or wdata.get("workspace", {}).get("configPath")
                                            if w_uri:
                                                wp = _uri_to_path(w_uri)
                                                if wp and wp.is_dir():
                                                    VSCodeAdapter._cached_workspace = wp
                                        except Exception:
                                            pass
                                    return p

                # 2. Try history.entries (recently focused files list)
                cur.execute("SELECT value FROM ItemTable WHERE key = 'history.entries'")
                row = cur.fetchone()
                if row:
                    entries = json.loads(row[0])
                    for item in entries:
                        res = item.get("editor", {}).get("resource", "")
                        if res:
                            p = _uri_to_path(res)
                            if p and p.is_file():
                                conn.close()
                                logger.info(f"Resolved active VS Code file from history.entries: {p}")
                                VSCodeAdapter._cached_file = p
                                ws_json = d / "workspace.json"
                                if ws_json.is_file():
                                    try:
                                        wdata = json.loads(ws_json.read_text(encoding="utf-8", errors="replace"))
                                        w_uri = wdata.get("folder") or wdata.get("workspace", {}).get("configPath")
                                        if w_uri:
                                            wp = _uri_to_path(w_uri)
                                            if wp and wp.is_dir():
                                                VSCodeAdapter._cached_workspace = wp
                                    except Exception:
                                        pass
                                return p

                conn.close()
            except Exception as e:
                logger.debug(f"Error querying {db_path}: {e}")

    return None


# ---------------------------------------------------------------------------
# Main adapter class
# ---------------------------------------------------------------------------

class VSCodeAdapter(EditorAdapter):
    """
    VS Code integration with 3-layer active-file detection:
      1. IPC extension state (live)
      2. globalStorage/storage.json workspace + window title filename
      3. Per-session path cache
    """

    # Class-level cache — persists across method calls within one session
    _cached_file: Optional[Path] = None
    _cached_workspace: Optional[Path] = None

    def is_available(self) -> bool:
        return ipc_server.state.is_active

    # ------------------------------------------------------------------
    # File detection
    # ------------------------------------------------------------------

    def _resolve_from_storage_and_title(self) -> Optional[Path]:
        """
        Step 2: read workspace from storage.json + filename from window title,
        search only inside the workspace folder (fast, bounded).
        """
        # Get workspace root
        workspace = _get_vscode_workspace_from_storage()
        if workspace:
            VSCodeAdapter._cached_workspace = workspace

        # Parse filename from window title
        titles = _get_vscode_window_titles()
        filename: Optional[str] = None
        for t in titles:
            fn = _parse_filename_from_title(t)
            if fn:
                filename = fn
                break

        if not filename:
            logger.debug("No filename found in VS Code window titles.")
            return None

        logger.debug(f"VS Code title suggests open file: '{filename}', workspace: {workspace}")

        # Search: workspace first (fast), then user home subfolders (depth-limited)
        search_roots: List[Path] = []
        if workspace and workspace.is_dir():
            search_roots.append(workspace)
        if VSCodeAdapter._cached_workspace and VSCodeAdapter._cached_workspace.is_dir():
            search_roots.append(VSCodeAdapter._cached_workspace)
        if VSCodeAdapter._cached_file:
            search_roots.append(VSCodeAdapter._cached_file.parent)

        # Add common user folders (limited depth)
        home = Path.home()
        for sub in ("Desktop", "Documents", "Downloads", "Projects", "Code", "dev", "src"):
            p = home / sub
            if p.is_dir():
                search_roots.append(p)

        # Deduplicate
        seen = set()
        unique_roots = []
        for r in search_roots:
            if r not in seen:
                seen.add(r)
                unique_roots.append(r)

        for root in unique_roots:
            try:
                # Depth-limited search (max 4 levels to stay fast)
                for match in _rglob_bounded(root, filename, max_depth=4):
                    logger.info(f"Resolved VS Code active file: {match}")
                    VSCodeAdapter._cached_file = match
                    return match
            except (PermissionError, OSError):
                pass

        return None

    def get_active_file(self) -> Optional[Path]:
        """
        Returns the currently focused file in VS Code.
        Layer 1 → IPC; Layer 2 → state.vscdb (live SQLite tab database); Layer 3 → storage+title; Layer 4 → cache.
        """
        # Layer 1: IPC extension (most accurate if extension active)
        if ipc_server.state.is_active and ipc_server.state.file_path:
            p = Path(ipc_server.state.file_path)
            if p.is_file():
                VSCodeAdapter._cached_file = p
                return p

        # Layer 2: state.vscdb (reads exact active tab directly from VS Code's internal database)
        vscdb_file = _resolve_from_vscdb()
        if vscdb_file:
            return vscdb_file

        # Layer 3: storage.json + window title
        found = self._resolve_from_storage_and_title()
        if found:
            return found

        # Layer 4: stale cache
        if VSCodeAdapter._cached_file and VSCodeAdapter._cached_file.is_file():
            logger.debug(f"Using cached VS Code file: {VSCodeAdapter._cached_file}")
            return VSCodeAdapter._cached_file

        return None

    def get_cursor_line(self) -> int:
        """Returns the 1-indexed cursor line number, or 1 if not available."""
        if ipc_server.state.cursor_line and ipc_server.state.cursor_line > 0:
            return ipc_server.state.cursor_line
        return 1

    def get_cursor_column(self) -> int:
        """Returns the 1-indexed cursor column number, or 1 if not available."""
        if ipc_server.state.cursor_column and ipc_server.state.cursor_column > 0:
            return ipc_server.state.cursor_column
        return 1

    def get_workspace(self) -> Optional[Path]:
        """Returns the current VS Code workspace folder."""
        if ipc_server.state.workspace_folder:
            return Path(ipc_server.state.workspace_folder)
        return _get_vscode_workspace_from_storage() or VSCodeAdapter._cached_workspace

    def get_workspace_roots(self) -> List[Path]:
        """Returns candidate workspace roots in priority order (deduplicated)."""
        roots: List[Path] = []
        active_f = self.get_active_file()
        if active_f and active_f.parent.is_dir():
            roots.append(active_f.parent)

        ws = self.get_workspace()
        if ws and ws.is_dir() and ws not in roots:
            roots.append(ws)

        if VSCodeAdapter._cached_workspace and VSCodeAdapter._cached_workspace.is_dir() and VSCodeAdapter._cached_workspace not in roots:
            roots.append(VSCodeAdapter._cached_workspace)

        if active_f and active_f.parent.parent.is_dir() and active_f.parent.parent not in roots:
            if len(active_f.parent.parent.parts) > 1:
                roots.append(active_f.parent.parent)

        if VSCodeAdapter._cached_file and VSCodeAdapter._cached_file.parent.is_dir() and VSCodeAdapter._cached_file.parent not in roots:
            roots.append(VSCodeAdapter._cached_file.parent)

        return roots

    def get_open_or_recent_files(self) -> List[Path]:
        """Returns existing file paths from VS Code history and workspace tab database."""
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return []
        results: List[Path] = []
        seen = set()
        for variant in ("Code", "Code - Insiders", "VSCodium"):
            ws_root = Path(appdata) / variant / "User" / "workspaceStorage"
            if not ws_root.is_dir():
                continue
            for d in ws_root.glob("*"):
                db_path = d / "state.vscdb"
                if not db_path.is_file():
                    continue
                try:
                    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.5)
                    cur = conn.cursor()
                    cur.execute("SELECT value FROM ItemTable WHERE key = 'history.entries'")
                    row = cur.fetchone()
                    if row:
                        entries = json.loads(row[0])
                        for item in entries:
                            res = item.get("editor", {}).get("resource", "")
                            if res:
                                p = _uri_to_path(res)
                                if p and p.is_file() and p not in seen:
                                    seen.add(p)
                                    results.append(p)
                    conn.close()
                except Exception:
                    pass
        return results

    def get_sibling_files(self) -> List[Path]:
        """Returns list of accessible files in the same directory as the active file."""
        active_f = self.get_active_file()
        if not active_f or not active_f.parent.is_dir():
            return []
        files: List[Path] = []
        try:
            for item in sorted(active_f.parent.iterdir()):
                if item.is_file() and not item.name.startswith(".") and not item.name.endswith(".bak"):
                    files.append(item)
        except Exception:
            pass
        return files

    def find_in_workspace(
        self,
        target: Union[str, Path],
        search_files: bool = True,
        search_folders: bool = True,
    ) -> Optional[Path]:
        """
        Locates a file or folder inside the active VS Code workspace or active directory.
        Checks:
          1. Direct child of active file's directory (sibling)
          2. Direct child of workspace root
          3. Exact / stem match against VS Code open/recent files
          4. Depth-limited recursive walk of workspace roots
        Supports:
          - Spoken prefixes & suffixes ("the file", "practical folder", "my file")
          - Normalization ignoring spaces, hyphens, underscores, dots, case
          - Stem matching and metaphone phonetic matching
          - Fuzzy similarity
        """
        if isinstance(target, Path):
            if target.exists():
                return target
            target = str(target)

        raw_clean = target.strip("'\" ").strip()
        if not raw_clean:
            return None

        # Check if already an existing absolute path
        try:
            direct_p = Path(raw_clean)
            if direct_p.is_absolute() and direct_p.exists():
                return direct_p
        except Exception:
            pass

        import jellyfish
        from rapidfuzz import fuzz

        def _normalize_name(s: str) -> str:
            return re.sub(r'[\s_\-.,]+', '', s.lower())

        cleaned_variants: List[str] = []
        c = raw_clean
        c = re.sub(r'(\w+)\s*\.\s*([a-zA-Z0-9]{1,6})\b', r'\1.\2', c)
        c = re.sub(r'\b(\w+)\s+dot\s+([a-zA-Z0-9]{1,6})\b', r'\1.\2', c)
        cleaned_variants.append(c)

        c_noprefix = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', c, flags=re.IGNORECASE).strip()
        if c_noprefix and c_noprefix not in cleaned_variants:
            cleaned_variants.append(c_noprefix)

        c_nosuffix = re.sub(r'\s+(?:folder|directory|project|workspace)$', '', c, flags=re.IGNORECASE).strip()
        if c_nosuffix and c_nosuffix not in cleaned_variants:
            cleaned_variants.append(c_nosuffix)

        c_both = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', c_nosuffix, flags=re.IGNORECASE).strip()
        if c_both and c_both not in cleaned_variants:
            cleaned_variants.append(c_both)

        c_nofile = re.sub(r'\s+file$', '', c, flags=re.IGNORECASE).strip()
        if c_nofile and c_nofile not in cleaned_variants:
            cleaned_variants.append(c_nofile)

        # Check phonetic mishearings of username / workspace items (e.g. android, camera, amrit -> amrat)
        for var in list(cleaned_variants):
            var_lower = var.lower()
            var_stem = Path(var_lower).stem
            ext = Path(var_lower).suffix
            if var_stem in ("android", "camera", "amrit", "amruth", "amrath", "amret", "emrat", "omrat", "imrat", "anrat", "anrod", "camrat", "kamrat", "am rat"):
                alias = f"amrat{ext}" if ext else "amrat"
                if alias not in cleaned_variants:
                    cleaned_variants.append(alias)

        roots = self.get_workspace_roots()

        for clean in cleaned_variants:
            has_ext = bool(re.search(r'\.[a-zA-Z0-9]{1,6}$', clean))
            clean_ext = Path(clean).suffix.lower() if has_ext else ""
            allow_folders = search_folders and not has_ext
            allow_files = search_files

            norm_clean = _normalize_name(clean)
            stem_clean = _normalize_name(Path(clean).stem)
            clean_meta = jellyfish.metaphone(Path(clean).stem) if Path(clean).stem else None

            # Step 1: Direct child of roots (exact and case/whitespace-insensitive)
            for root in roots:
                if not root or not root.is_dir():
                    continue
                cand = root / clean
                if cand.exists():
                    if (cand.is_file() and allow_files) or (cand.is_dir() and allow_folders):
                        return cand

                try:
                    for child in root.iterdir():
                        c_norm = _normalize_name(child.name)
                        c_stem_norm = _normalize_name(child.stem)
                        c_ext = child.suffix.lower()
                        ext_compatible = (not has_ext) or (c_ext == clean_ext)

                        if (c_norm == norm_clean or (not has_ext and c_stem_norm == norm_clean)):
                            if (child.is_file() and allow_files) or (child.is_dir() and allow_folders):
                                return child
                        if ext_compatible and clean_meta and jellyfish.metaphone(child.stem) == clean_meta:
                            if (child.is_file() and allow_files) or (child.is_dir() and allow_folders):
                                return child
                        if ext_compatible and fuzz.ratio(c_stem_norm, stem_clean) >= 85:
                            if (child.is_file() and allow_files) or (child.is_dir() and allow_folders):
                                return child
                except (PermissionError, OSError):
                    pass

            # Step 2: Bounded walk within workspace roots (depth <= 4)
            ignored = {"node_modules", ".git", ".vscode", "__pycache__", "venv", "myenv", ".venv", "env", "appdata", "dist", "build"}

            for root in roots:
                if not root or not root.is_dir():
                    continue
                root_str = str(root)
                try:
                    for dirpath, dirnames, filenames in os.walk(root_str):
                        depth = dirpath.replace(root_str, "").count(os.sep)
                        dirnames[:] = [d for d in dirnames if d.lower() not in ignored and not d.startswith(".")]

                        if allow_folders and depth > 0:
                            d_name = os.path.basename(dirpath)
                            if _normalize_name(d_name) == norm_clean or fuzz.ratio(_normalize_name(d_name), norm_clean) >= 90:
                                return Path(dirpath)

                        if allow_files:
                            for fn in filenames:
                                fn_norm = _normalize_name(fn)
                                fn_stem_norm = _normalize_name(Path(fn).stem)
                                fn_ext = Path(fn).suffix.lower()
                                ext_compatible = (not has_ext) or (fn_ext == clean_ext)

                                if fn_norm == norm_clean or (not has_ext and fn_stem_norm == norm_clean):
                                    return Path(dirpath) / fn
                                if ext_compatible and clean_meta and jellyfish.metaphone(Path(fn).stem) == clean_meta and fuzz.ratio(fn_stem_norm, stem_clean) >= 70:
                                    return Path(dirpath) / fn
                                if ext_compatible and fuzz.ratio(fn_stem_norm, stem_clean) >= 88:
                                    return Path(dirpath) / fn

                        if depth >= 4:
                            dirnames.clear()
                except (PermissionError, OSError):
                    pass

            # Step 3: Open or recent files in VS Code (fallback if not found in workspace roots)
            if allow_files:
                for rf in self.get_open_or_recent_files():
                    rf_norm = _normalize_name(rf.name)
                    rf_stem_norm = _normalize_name(rf.stem)
                    rf_ext = rf.suffix.lower()
                    ext_compatible = (not has_ext) or (rf_ext == clean_ext)

                    if rf_norm == norm_clean or (not has_ext and rf_stem_norm == norm_clean):
                        return rf
                    if ext_compatible and clean_meta and jellyfish.metaphone(rf.stem) == clean_meta and fuzz.ratio(rf_stem_norm, stem_clean) >= 70:
                        return rf
                    if ext_compatible and fuzz.ratio(rf_stem_norm, stem_clean) >= 85:
                        return rf

        return None

    def open_folder(self, folder_path: Path) -> bool:
        """Opens a folder in VS Code, activating the window."""
        try:
            code_bin = self._get_code_cli()
            subprocess.Popen([code_bin, "--reuse-window", str(folder_path)], shell=(sys.platform == "win32"))
            VSCodeAdapter._cached_workspace = folder_path
            try:
                from app.platform_layer import platform_adapter
                platform_adapter.focus_window("vscode")
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"Failed to open folder {folder_path} in VS Code: {e}")
            return False

    def next_file(self) -> bool:
        """Switches to the next editor tab in VS Code."""
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.focus_window("vscode")
            import time
            time.sleep(0.05)
            if sys.platform == "darwin":
                platform_adapter.send_hotkey("command", "option", "right")
            else:
                platform_adapter.send_hotkey("ctrl", "pagedown")
            return True
        except Exception as e:
            logger.error(f"Failed to switch to next file: {e}")
            return False

    def previous_file(self) -> bool:
        """Switches to the previous editor tab in VS Code."""
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.focus_window("vscode")
            import time
            time.sleep(0.05)
            if sys.platform == "darwin":
                platform_adapter.send_hotkey("command", "option", "left")
            else:
                platform_adapter.send_hotkey("ctrl", "pageup")
            return True
        except Exception as e:
            logger.error(f"Failed to switch to previous file: {e}")
            return False

    # ------------------------------------------------------------------
    # Document content
    # ------------------------------------------------------------------

    def read_document(self, file_path: Optional[Path] = None) -> Optional[str]:
        """Reads document content: IPC memory → explicit path → active file → disk."""
        # IPC has live in-memory content (most up-to-date, includes unsaved changes)
        if file_path is None and ipc_server.state.document_text:
            return ipc_server.state.document_text

        target = file_path or self.get_active_file()
        if target and target.is_file():
            try:
                return target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return target.read_text(encoding="cp1252", errors="replace")
            except Exception as e:
                logger.error(f"Failed to read {target}: {e}")
        return None

    # ------------------------------------------------------------------
    # Editor commands
    # ------------------------------------------------------------------

    @staticmethod
    def _get_code_cli() -> str:
        """Resolves the 'code' CLI path cross-platform via platform_adapter, then PATH fallback."""
        try:
            from app.platform_layer import platform_adapter
            exe = platform_adapter.get_vscode_executable()
            if exe:
                return exe
        except Exception:
            pass
        import shutil
        return shutil.which("code") or "code"

    def jump_to_line(self, line_number: int) -> bool:
        """
        Jumps to and reveals a line in VS Code.
        Layer 1: IPC extension (in-process revealRange in center).
        Layer 2: CLI code --reuse-window --goto <file>:<line>.
        Layer 3: Keyboard automation fallback (Quick Open goto line / Ctrl+G).
        Also ensures the VS Code window is activated and brought to the foreground.
        """
        # Ensure VS Code window is visible and focused first so jump and scroll are immediately visible
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.focus_window("vscode")
        except Exception:
            pass

        jumped = False

        # Layer 1: IPC extension
        if self.is_available():
            import uuid
            res = _ipc_post("/vscode/enqueue_command", {
                "id": str(uuid.uuid4()), "action": "jump_to_line",
                "params": {"line_number": line_number}
            })
            if res.get("success"):
                jumped = True
                logger.info(f"Jumped to line {line_number} via VS Code IPC extension.")

        # Layer 2: CLI code --reuse-window --goto <file>:<line>
        if not jumped:
            active_file = self.get_active_file()
            if active_file:
                try:
                    code_bin = self._get_code_cli()
                    subprocess.Popen([code_bin, "--reuse-window", "--goto",
                                      f"{active_file}:{line_number}"], shell=(sys.platform == "win32"))
                    jumped = True
                    logger.info(f"Jumped to line {line_number} of {active_file.name} via CLI.")
                except Exception as e:
                    logger.error(f"CLI jump failed: {e}")

        # Layer 3: Keyboard automation fallback (Ctrl+G -> line_number -> Enter)
        if not jumped:
            try:
                from app.platform_layer import platform_adapter
                platform_adapter.focus_window("code")
                import time
                time.sleep(0.05)
                platform_adapter.send_hotkey("ctrl", "g")
                time.sleep(0.08)
                platform_adapter.type_text(str(line_number))
                time.sleep(0.05)
                platform_adapter.press_key("enter")
                jumped = True
                logger.info(f"Jumped to line {line_number} via Ctrl+G hotkey.")
            except Exception as e:
                logger.warning(f"Failed to send Ctrl+G: {e}")


        # Ensure VS Code window is visible and focused so the user actually sees the line
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.focus_window("vscode")
        except Exception:
            pass

        return jumped

    def open_file(self, file_path: Path, line_number: Optional[int] = None) -> bool:
        """
        Opens / reloads a file in VS Code using --reuse-window so we don't
        spawn a second window after every programmatic edit.
        If file_path is a directory, opens the directory as a workspace.
        """
        if file_path and file_path.is_dir():
            return self.open_folder(file_path)
        try:
            code_bin = self._get_code_cli()
            cmd = [code_bin, "--reuse-window"]
            if line_number:
                cmd.extend(["--goto", f"{file_path}:{line_number}"])
            else:
                cmd.append(str(file_path))
            subprocess.Popen(cmd, shell=(sys.platform == "win32"))
            VSCodeAdapter._cached_file = file_path
            try:
                from app.platform_layer import platform_adapter
                platform_adapter.focus_window("vscode")
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"Failed to open {file_path} in VS Code: {e}")
            return False

        except Exception as e:
            logger.error(f"Failed to open {file_path} in VS Code: {e}")
            return False

    def close_file(self, file_path: Optional[str] = None) -> str:
        """
        Closes the active editor tab (or a specific file tab) in VS Code.
        Layer 1: IPC extension command if connected.
        Layer 2: Keyboard shortcut (Ctrl+W) via Windows input automation.
        Also clears cached file reference and updates conversational memory.
        """
        active_f = self.get_active_file()
        display_name = Path(file_path).name if file_path else (active_f.name if active_f else "active file")

        closed = False

        # Layer 1: IPC extension
        if self.is_available():
            import uuid
            res = _ipc_post("/vscode/enqueue_command", {
                "id": str(uuid.uuid4()),
                "action": "close_file",
                "params": {"file_path": file_path}
            })
            if res.get("success"):
                closed = True
                logger.info(f"Closed {display_name} via VS Code IPC extension.")

        # Layer 2: Keyboard automation fallback (Ctrl+W)
        if not closed:
            try:
                from app.platform_layer import platform_adapter
                platform_adapter.send_hotkey("ctrl", "w")
                closed = True
                logger.info(f"Closed {display_name} via Ctrl+W hotkey.")
            except Exception as e:
                logger.warning(f"Failed to send Ctrl+W: {e}")

        # Clear cached file reference
        VSCodeAdapter._cached_file = None
        try:
            from app.memory.conversation import conversation_memory
            if conversation_memory.last_file:
                conversation_memory.last_file = None
        except Exception:
            pass

        if closed:
            return f"Closed {display_name} in VS Code."
        else:
            return f"Could not close {display_name}."

    def apply_edit(
        self,
        file_path: Path,
        start_line: int,
        end_line: int,
        new_text: str,
        start_col: int = 0,
        end_col: int = 0,
    ) -> bool:
        """IPC first; programmatic file edit as fallback."""
        if self.is_available():
            import uuid
            res = _ipc_post("/vscode/enqueue_command", {
                "id": str(uuid.uuid4()), "action": "apply_edit",
                "params": {
                    "start_line": start_line, "end_line": end_line,
                    "start_col": start_col, "end_col": end_col, "new_text": new_text,
                }
            })
            if res.get("success"):
                return True
            logger.debug(f"IPC apply_edit failed, using file fallback: {res.get('error')}")

        if not file_path.is_file():
            return False
        try:
            bak = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copy2(file_path, bak)
            raw = file_path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")
            lines = text.splitlines(keepends=True)
            s = max(0, start_line - 1)
            e = min(len(lines), end_line)
            # Detect EOL from file
            eol = "\r\n" if text.count("\r\n") >= text.count("\n") - text.count("\r\n") else "\n"

            # Preserve leading indentation if original line had indentation and new_text doesn't specify its own
            indent = ""
            if 0 <= s < len(lines):
                orig_line = lines[s]
                indent = orig_line[:len(orig_line) - len(orig_line.lstrip(" \t"))]

            chunks = []
            for idx_line, raw_chunk in enumerate(new_text.splitlines()):
                if indent and not raw_chunk.startswith((" ", "\t")) and (idx_line == 0 or not raw_chunk.strip().startswith("#")):
                    chunks.append(indent + raw_chunk.rstrip("\r\n") + eol)
                else:
                    chunks.append(raw_chunk.rstrip("\r\n") + eol)

            if not chunks:
                chunks = [eol]

            # Record original content in code_patch_engine undo stack
            try:
                from app.editor.code_patch_engine import code_patch_engine
                orig_text, orig_eol = code_patch_engine.read_file_with_eol(file_path)
                code_patch_engine._undo_history.append({
                    "path": file_path,
                    "original_content": orig_text,
                    "modified_content": "".join(lines[:s] + chunks + lines[e:]),
                    "diff": "",
                    "explanation": f"Line edit in {file_path.name}",
                    "eol": orig_eol
                })
            except Exception:
                pass

            lines[s:e] = chunks
            file_path.write_bytes("".join(lines).encode("utf-8"))
            return True
        except Exception as ex:
            logger.error(f"File-level edit failed: {ex}")
            return False

    def save(self) -> bool:
        if self.is_available():
            import uuid
            res = _ipc_post("/vscode/enqueue_command", {
                "id": str(uuid.uuid4()), "action": "save_document", "params": {}
            })
            if res.get("success"):
                return True
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.send_hotkey("ctrl", "s")
            return True
        except Exception:
            pass
        return False


    def run_code(self) -> bool:
        if self.is_available():
            import uuid
            res = _ipc_post("/vscode/enqueue_command", {
                "id": str(uuid.uuid4()), "action": "run_code", "params": {}
            })
            if res.get("success"):
                return True
        active_file = self.get_active_file()
        if active_file and active_file.is_file():
            if active_file.suffix == ".py":
                try:
                    from app.platform_layer import platform_adapter
                    platform_adapter.run_user_code_in_terminal(active_file)
                    return True
                except Exception:
                    # Fallback: launch with sys.executable in a detached process
                    import sys as _sys
                    subprocess.Popen([_sys.executable, str(active_file)],
                                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
                    return True
        return False


    def undo(self) -> bool:
        # 1. Try code_patch_engine (semantic in-memory history & disk backup)
        try:
            from app.editor.code_patch_engine import code_patch_engine
            active_file = self.get_active_file()
            ok, _ = code_patch_engine.undo_last_patch(active_file)
            if ok:
                reverted_file = getattr(code_patch_engine, 'last_reverted_path', None) or active_file
                if reverted_file:
                    self.open_file(reverted_file)
                return True
        except Exception as e:
            logger.debug(f"code_patch_engine undo check failed: {e}")

        # 2. Try IPC
        if self.is_available():
            import uuid
            res = _ipc_post("/vscode/enqueue_command", {
                "id": str(uuid.uuid4()), "action": "undo", "params": {}
            })
            if res.get("success"):
                return True

        # 3. Try .bak file on disk
        active_file = self.get_active_file()
        if active_file:
            bak = active_file.with_suffix(active_file.suffix + ".bak")
            if bak.is_file():
                shutil.copy2(bak, active_file)
                logger.info(f"Restored {active_file} from backup")
                self.open_file(active_file)
                return True

        # 4. Try keyboard shortcut fallback in active editor
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "z")
            return True
        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # Extended VS Code actions (proxied through IPC extension actions)
    # ------------------------------------------------------------------

    def _ipc_command(self, action: str, params: dict) -> bool:
        """Send any named action to the extension via IPC and return success flag."""
        if not self.is_available():
            return False
        import uuid
        res = _ipc_post("/vscode/enqueue_command", {
            "id": str(uuid.uuid4()), "action": action, "params": params
        })
        if not res.get("success"):
            logger.debug(f"IPC {action} failed: {res.get('error')}")
        return bool(res.get("success"))

    def delete_lines(self, start_line: int, end_line: int) -> bool:
        """Delete lines [start_line, end_line] (1-indexed, inclusive) via IPC or disk fallback."""
        if self._ipc_command("delete_lines", {"start_line": start_line, "end_line": end_line}):
            return True
        fp = self.get_active_file()
        if fp and fp.is_file():
            try:
                bak = fp.with_suffix(fp.suffix + ".bak")
                shutil.copy2(fp, bak)
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                s, e = max(0, start_line - 1), min(len(lines), end_line)
                del lines[s:e]
                fp.write_text("".join(lines), encoding="utf-8")
                return True
            except Exception as ex:
                logger.error(f"delete_lines disk fallback failed: {ex}")
        return False

    def insert_line(self, line_number: int, text: str) -> bool:
        """Insert `text` as a new line before `line_number` (1-indexed) via IPC or disk fallback."""
        if self._ipc_command("insert_line", {"line_number": line_number, "text": text}):
            return True
        fp = self.get_active_file()
        if fp and fp.is_file():
            try:
                bak = fp.with_suffix(fp.suffix + ".bak")
                shutil.copy2(fp, bak)
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                idx = max(0, min(line_number - 1, len(lines)))
                eol = "\r\n" if lines and "\r\n" in lines[0] else "\n"
                lines.insert(idx, text.rstrip("\r\n") + eol)
                fp.write_text("".join(lines), encoding="utf-8")
                return True
            except Exception as ex:
                logger.error(f"insert_line disk fallback failed: {ex}")
        return False

    def replace_line(self, line_number: int, new_text: str) -> bool:
        """Replace the content of `line_number` (1-indexed) with `new_text`."""
        if self._ipc_command("replace_line", {"line_number": line_number, "new_text": new_text}):
            return True
        fp = self.get_active_file() or Path("/dev/null")
        return self.apply_edit(fp, line_number, line_number, new_text)

    def find_and_replace(self, search: str, replace: str, use_regex: bool = False) -> bool:
        """Find-and-replace all occurrences in the active document (IPC only)."""
        return self._ipc_command(
            "find_and_replace",
            {"search": search, "replace": replace, "use_regex": use_regex}
        )

    def redo(self) -> bool:
        """Redo last undone edit in VS Code."""
        if self._ipc_command("redo", {}):
            return True
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.send_hotkey("ctrl", "y")
            return True
        except Exception:
            pass
        return False

    def format_document(self) -> bool:
        """Trigger VS Code's Format Document action."""
        if self._ipc_command("format_document", {}):
            return True
        try:
            from app.platform_layer import platform_adapter
            platform_adapter.send_hotkey("shift", "alt", "f")
            return True
        except Exception:
            pass
        return False

    def toggle_comment(self, line_number: int, end_line: int = 0) -> bool:
        """Toggle line comment for the given line range (1-indexed)."""
        params: dict = {"line_number": line_number}
        if end_line and end_line != line_number:
            params["end_line"] = end_line
        return self._ipc_command("toggle_comment", params)

    def duplicate_line(self, line_number: int = 0) -> bool:
        """Duplicate the given line (or current cursor line when 0)."""
        params: dict = {}
        if line_number:
            params["line_number"] = line_number
        return self._ipc_command("duplicate_line", params)

    def go_to_definition(self) -> bool:
        """Jump to the definition of the symbol under the cursor."""
        return self._ipc_command("go_to_definition", {})

    def move_line_up(self, count: int = 1) -> bool:
        """Move the current cursor line up `count` times."""
        return self._ipc_command("move_line_up", {"count": count})

    def move_line_down(self, count: int = 1) -> bool:
        """Move the current cursor line down `count` times."""
        return self._ipc_command("move_line_down", {"count": count})

    def select_line(self, line_number: int = 0) -> bool:
        """Select entire line `line_number` (or cursor line if 0) in VS Code."""
        params: dict = {}
        if line_number:
            params["line_number"] = line_number
        return self._ipc_command("select_line", params)

    def get_vscode_context(self) -> Dict[str, Any]:
        active = self.get_active_file()
        return {
            "active_file": str(active) if active else None,
            "workspace_folder": str(self.get_workspace()) if self.get_workspace() else None,
            "cursor_line": ipc_server.state.cursor_line,
            "ipc_connected": ipc_server.state.is_active,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rglob_bounded(root: Path, filename: str, max_depth: int) -> List[Path]:
    """Walk `root` up to `max_depth` directory levels looking for `filename`."""
    results: List[Path] = []
    root_str = str(root)
    try:
        for dirpath, dirnames, filenames in os.walk(root_str):
            # Compute current depth relative to root
            depth = dirpath.replace(root_str, "").count(os.sep)
            if filename in filenames:
                results.append(Path(dirpath) / filename)
            if depth >= max_depth:
                dirnames.clear()  # prune — don't descend further
    except (PermissionError, OSError):
        pass
    return results



