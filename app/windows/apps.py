import json
import os
import re
import shutil
import subprocess
import threading
import winreg
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import psutil
from rapidfuzz import fuzz

try:
    import win32con
    import win32gui
    import win32process
    import pythoncom
    import win32com.client
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

from app.logging.logger import logger
from app.speech.normalizer import speech_normalizer


class WindowsAppCatalog:
    """
    Intelligently locates, activates, launches, and closes Windows applications.
    Indexes Start Menu shortcuts (.lnk), UWP applications (Get-StartApps),
    Registry App Paths, PATH, and running processes with persistent disk caching.
    """

    BUILTIN_APPS: Dict[str, Dict[str, Any]] = {
        "vscode": {
            "canonical": "Visual Studio Code",
            "aliases": ["vs code", "vscode", "code", "visual studio code"],
            "executables": ["code.cmd", "code.exe"],
            "process_names": ["code.exe"],
        },
        "chrome": {
            "canonical": "Google Chrome",
            "aliases": ["chrome", "google chrome", "browser"],
            "executables": ["chrome.exe"],
            "process_names": ["chrome.exe"],
        },
        "edge": {
            "canonical": "Microsoft Edge",
            "aliases": ["edge", "microsoft edge", "ms edge"],
            "executables": ["msedge.exe"],
            "process_names": ["msedge.exe"],
        },
        "brave": {
            "canonical": "Brave Browser",
            "aliases": ["brave", "brave browser"],
            "executables": ["brave.exe"],
            "process_names": ["brave.exe"],
        },
        "firefox": {
            "canonical": "Firefox",
            "aliases": ["firefox", "mozilla firefox"],
            "executables": ["firefox.exe"],
            "process_names": ["firefox.exe"],
        },
        "notepad": {
            "canonical": "Notepad",
            "aliases": ["notepad", "text editor", "note pad"],
            "executables": ["notepad.exe"],
            "process_names": ["notepad.exe"],
        },
        "calculator": {
            "canonical": "Calculator",
            "aliases": ["calculator", "calc"],
            "executables": ["calc.exe"],
            "process_names": ["calculatorapp.exe", "calc.exe"],
        },
        "explorer": {
            "canonical": "File Explorer",
            "aliases": ["file explorer", "explorer", "files", "my files", "open files"],
            "executables": ["explorer.exe"],
            "process_names": ["explorer.exe"],
        },
        "cmd": {
            "canonical": "Command Prompt",
            "aliases": ["command prompt", "cmd", "terminal prompt"],
            "executables": ["cmd.exe"],
            "process_names": ["cmd.exe"],
        },
        "powershell": {
            "canonical": "PowerShell",
            "aliases": ["powershell", "windows powershell", "pwsh"],
            "executables": ["powershell.exe", "pwsh.exe"],
            "process_names": ["powershell.exe", "pwsh.exe"],
        },
        "terminal": {
            "canonical": "Windows Terminal",
            "aliases": ["windows terminal", "terminal", "wt"],
            "executables": ["wt.exe"],
            "process_names": ["windowsterminal.exe", "wt.exe"],
        },
        "taskmgr": {
            "canonical": "Task Manager",
            "aliases": ["task manager", "taskmgr", "task mgr"],
            "executables": ["taskmgr.exe"],
            "process_names": ["taskmgr.exe"],
        },
        "control": {
            "canonical": "Control Panel",
            "aliases": ["control panel", "control"],
            "executables": ["control.exe"],
            "process_names": ["control.exe"],
        },
        "spotify": {
            "canonical": "Spotify",
            "aliases": ["spotify", "music player"],
            "executables": ["spotify.exe"],
            "process_names": ["spotify.exe"],
        },
        "slack": {
            "canonical": "Slack",
            "aliases": ["slack"],
            "executables": ["slack.exe"],
            "process_names": ["slack.exe"],
        },
        "discord": {
            "canonical": "Discord",
            "aliases": ["discord"],
            "executables": ["discord.exe", "update.exe --processStart Discord.exe"],
            "process_names": ["discord.exe"],
        },
        "pycharm": {
            "canonical": "PyCharm",
            "aliases": ["pycharm", "pi charm", "pie charm"],
            "executables": ["pycharm64.exe", "pycharm.exe"],
            "process_names": ["pycharm64.exe", "pycharm.exe"],
        },
        "postgresql": {
            "canonical": "PostgreSQL",
            "aliases": ["postgresql", "postgres", "post grey sql", "postgre sql", "postgres sql", "pgadmin"],
            "executables": ["pgadmin4.exe", "psql.exe"],
            "process_names": ["pgadmin4.exe", "postgres.exe"],
        },
        "word": {
            "canonical": "Microsoft Word",
            "aliases": ["word", "microsoft word", "ms word"],
            "executables": ["winword.exe"],
            "process_names": ["winword.exe"],
        },
        "excel": {
            "canonical": "Microsoft Excel",
            "aliases": ["excel", "microsoft excel", "ms excel"],
            "executables": ["excel.exe"],
            "process_names": ["excel.exe"],
        },
        "powerpoint": {
            "canonical": "Microsoft PowerPoint",
            "aliases": ["powerpoint", "microsoft powerpoint", "ppt"],
            "executables": ["powerpnt.exe"],
            "process_names": ["powerpnt.exe"],
        },
        "cursor": {
            "canonical": "Cursor",
            "aliases": ["cursor", "cursor editor"],
            "executables": ["cursor.exe"],
            "process_names": ["cursor.exe"],
        },
        "antigravity": {
            "canonical": "Antigravity",
            "aliases": ["antigravity", "antigravity ide", "anti gravity"],
            "executables": ["antigravity.exe", "agy.exe"],
            "process_names": ["antigravity.exe", "agy.exe"],
        },
    }

    # Known installation paths searched when shutil.which() returns None.
    # Keys match the keys in BUILTIN_APPS.  Values are lists of candidate paths
    # that may contain {LOCALAPPDATA}, {APPDATA}, {ProgramFiles}, {ProgramFiles86},
    # {USERPROFILE} placeholders — expanded at runtime.
    _KNOWN_PATHS: Dict[str, List[str]] = {
        "chrome": [
            r"{ProgramFiles86}\Google\Chrome\Application\chrome.exe",
            r"{ProgramFiles}\Google\Chrome\Application\chrome.exe",
            r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
        ],
        "brave": [
            r"{LOCALAPPDATA}\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"{ProgramFiles}\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"{ProgramFiles86}\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "edge": [
            r"{ProgramFiles86}\Microsoft\Edge\Application\msedge.exe",
            r"{ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
            r"{LOCALAPPDATA}\Microsoft\Edge\Application\msedge.exe",
        ],
        "firefox": [
            r"{ProgramFiles}\Mozilla Firefox\firefox.exe",
            r"{ProgramFiles86}\Mozilla Firefox\firefox.exe",
        ],
        "vscode": [
            r"{LOCALAPPDATA}\Programs\Microsoft VS Code\Code.exe",
            r"{ProgramFiles}\Microsoft VS Code\Code.exe",
            r"{ProgramFiles86}\Microsoft VS Code\Code.exe",
        ],
        "pycharm": [
            r"{ProgramFiles}\JetBrains\PyCharm Community Edition\bin\pycharm64.exe",
            r"{ProgramFiles}\JetBrains\PyCharm Professional Edition\bin\pycharm64.exe",
            r"{LOCALAPPDATA}\JetBrains\Toolbox\apps\PyCharm-C\ch-0\bin\pycharm64.exe",
        ],
        "spotify": [
            r"{APPDATA}\Spotify\Spotify.exe",
            r"{LOCALAPPDATA}\Microsoft\WindowsApps\Spotify.exe",
        ],
        "discord": [
            r"{LOCALAPPDATA}\Discord\Update.exe",
            r"{LOCALAPPDATA}\Discord\app-{version}\Discord.exe",
        ],
        "cursor": [
            r"{LOCALAPPDATA}\Programs\cursor\Cursor.exe",
            r"{APPDATA}\cursor\Cursor.exe",
        ],
    }

    @classmethod
    def _expand_known_paths(cls, key: str) -> Optional[str]:
        """
        Returns the first existing path from _KNOWN_PATHS[key] after expanding
        environment-variable placeholders.  Returns None if none exists.
        Templates may use {ProgramFiles}, {ProgramFiles86}, {LOCALAPPDATA},
        {APPDATA}, {USERPROFILE}.  Any template containing unknown placeholders
        (e.g. {version}) is treated as a glob pattern — the first match wins.
        """
        import glob as _glob
        candidates = cls._KNOWN_PATHS.get(key, [])
        env = {
            "ProgramFiles":   os.environ.get("ProgramFiles",   r"C:\Program Files"),
            "ProgramFiles86": os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            "LOCALAPPDATA":   os.environ.get("LOCALAPPDATA",   str(Path.home() / "AppData" / "Local")),
            "APPDATA":        os.environ.get("APPDATA",        str(Path.home() / "AppData" / "Roaming")),
            "USERPROFILE":    os.environ.get("USERPROFILE",    str(Path.home())),
        }
        for template in candidates:
            try:
                path = template.format(**env)
                if os.path.exists(path):
                    return path
            except KeyError:
                # Template has an unknown placeholder like {version} — treat as glob
                try:
                    # Replace known placeholders first, then use * for unknown ones
                    import re as _re
                    partial = template
                    for k, v in env.items():
                        partial = partial.replace("{" + k + "}", v)
                    # Replace remaining {anything} with * for glob
                    glob_pattern = _re.sub(r"\{[^}]+\}", "*", partial)
                    matches = sorted(_glob.glob(glob_pattern))
                    if matches:
                        return matches[-1]   # pick latest (highest version sorts last)
                except Exception:
                    pass
        return None



    def __init__(self):
        self._lock = threading.Lock()
        self._catalog: Dict[str, Dict[str, Any]] = {}
        self._cache_file = self._get_cache_path()
        self._load_cache()
        # Trigger background indexing
        threading.Thread(target=self.refresh_index, args=(False,), daemon=True, name="Clembot-AppIndexer").start()

    @classmethod
    def _get_cache_path(cls) -> Path:
        cache_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Clembot"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "app_index.json"

    def _normalize(self, text: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

    def _load_cache(self) -> None:
        """Loads cached app index from disk if available."""
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))
                with self._lock:
                    self._catalog = data
                logger.info(f"Loaded {len(self._catalog)} indexed apps from {self._cache_file}")
            except Exception as e:
                logger.warning(f"Failed to load app index cache: {e}")

    def _save_cache(self) -> None:
        """Saves current in-memory catalog to disk cache."""
        try:
            with self._lock:
                data = dict(self._catalog)
            self._cache_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(f"Saved {len(data)} indexed apps to {self._cache_file}")
        except Exception as e:
            logger.warning(f"Failed to write app index cache: {e}")

    def refresh_index(self, force: bool = False) -> None:
        """Indexes Start Menu shortcuts, UWP apps, Registry App Paths, and Local Programs."""
        new_catalog: Dict[str, Dict[str, Any]] = {}

        # 1. Index built-in apps — resolve real exe path now so the catalog is usable
        for key, entry in self.BUILTIN_APPS.items():
            norm_key = self._normalize(key)
            # Try to resolve to a real on-disk path
            resolved_target: str = entry["executables"][0]
            resolved_type: str = "system"
            for exe in entry["executables"]:
                found = shutil.which(exe)
                if found:
                    resolved_target = found
                    resolved_type = "exe"
                    break
            if resolved_type != "exe":
                known = self._expand_known_paths(key)
                if known:
                    resolved_target = known
                    resolved_type = "exe"
            new_catalog[norm_key] = {
                "name": entry["canonical"],
                "type": resolved_type,
                "target": resolved_target,
                "executables": entry["executables"],
                "process_names": entry["process_names"],
                "aliases": entry["aliases"]
            }


        # 2. Index Start Menu Shortcuts (.lnk) with target resolution
        self._index_shortcuts(new_catalog)

        # 3. Index UWP Store Apps via Get-StartApps
        self._index_uwp_apps(new_catalog)

        # 4. Index Registry App Paths
        self._index_registry_apps(new_catalog)

        with self._lock:
            self._catalog.update(new_catalog)

        self._save_cache()

    def _index_shortcuts(self, catalog: Dict[str, Dict[str, Any]]) -> None:
        """Scans Start Menu and Desktop shortcuts, resolving real .lnk targets via COM."""
        start_menu_roots = [
            Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft\\Windows\\Start Menu\\Programs",
            Path(os.environ.get("APPDATA", "")) / "Microsoft\\Windows\\Start Menu\\Programs",
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(os.environ.get("PUBLIC", "C:\\Users\\Public")) / "Desktop",
        ]

        wscript = None
        if HAS_WIN32:
            try:
                pythoncom.CoInitialize()
                wscript = win32com.client.Dispatch("WScript.Shell")
            except Exception as e:
                logger.debug(f"Could not initialize WScript.Shell: {e}")

        for root in start_menu_roots:
            if not root.is_dir():
                continue
            for lnk in root.rglob("*.lnk"):
                try:
                    stem = lnk.stem
                    norm_stem = self._normalize(stem)
                    target_exe = str(lnk)
                    if wscript:
                        try:
                            sc = wscript.CreateShortcut(str(lnk))
                            if sc.TargetPath and os.path.exists(sc.TargetPath):
                                target_exe = sc.TargetPath
                        except Exception:
                            pass

                    catalog[norm_stem] = {
                        "name": stem,
                        "type": "lnk",
                        "target": target_exe,
                        "lnk_path": str(lnk),
                        "aliases": [stem.lower()]
                    }
                except Exception:
                    continue

    def _index_uwp_apps(self, catalog: Dict[str, Dict[str, Any]]) -> None:
        """Queries Windows modern UWP apps via Get-StartApps."""
        try:
            cmd = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-StartApps | ConvertTo-Json -Compress"'
            output = subprocess.check_output(cmd, shell=True, text=True, timeout=8, stderr=subprocess.DEVNULL)
            if not output.strip():
                return
            apps_data = json.loads(output)
            if isinstance(apps_data, dict):
                apps_data = [apps_data]

            for item in apps_data:
                name = item.get("Name", "")
                appid = item.get("AppID", "")
                if name and appid:
                    norm_name = self._normalize(name)
                    catalog[norm_name] = {
                        "name": name,
                        "type": "uwp",
                        "target": appid,
                        "aliases": [name.lower()]
                    }
        except Exception as e:
            logger.debug(f"Get-StartApps query skipped or failed: {e}")

    def _index_registry_apps(self, catalog: Dict[str, Dict[str, Any]]) -> None:
        """Scans Windows Registry 'App Paths' keys."""
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        ]
        for hkey, subkey_path in keys:
            try:
                with winreg.OpenKey(hkey, subkey_path) as root_key:
                    index = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(root_key, index)
                            index += 1
                            stem = sub_name[:-4] if sub_name.lower().endswith(".exe") else sub_name
                            norm_stem = self._normalize(stem)
                            with winreg.OpenKey(root_key, sub_name) as app_key:
                                val, _ = winreg.QueryValueEx(app_key, "")
                                if val and os.path.exists(val) and norm_stem not in catalog:
                                    catalog[norm_stem] = {
                                        "name": stem,
                                        "type": "exe",
                                        "target": val,
                                        "aliases": [stem.lower()]
                                    }
                        except OSError:
                            break
            except OSError:
                continue

    def find_executable(self, spoken_name: str) -> Optional[Tuple[str, str]]:
        """
        Resolves spoken name to (launch_target, app_type) e.g. ("C:\\...\\code.exe", "exe") or (AppID, "uwp").
        Uses homophone normalization and RapidFuzz fuzzy candidate selection.
        """
        # 1. Normalize homophones (e.g. "post grey sql" -> "postgresql")
        norm_spoken = speech_normalizer.replace_homophones(spoken_name.strip().lower())
        clean_key = self._normalize(norm_spoken)

        # 2. Check built-in mappings
        for key, entry in self.BUILTIN_APPS.items():
            if clean_key == self._normalize(key) or clean_key == self._normalize(entry["canonical"]) or any(clean_key == self._normalize(a) for a in entry["aliases"]):
                # a) shutil.which — works when app is in PATH
                for exe in entry["executables"]:
                    which_path = shutil.which(exe)
                    if which_path:
                        return which_path, "exe"

                # b) Known fixed install paths (e.g. Chrome in Program Files)
                known = self._expand_known_paths(key)
                if known:
                    logger.debug(f"Resolved '{spoken_name}' via known path: {known}")
                    return known, "exe"

                # c) Windows system built-ins that are always launchable by name
                SYSTEM_BUILTINS = {"calc.exe", "notepad.exe", "explorer.exe",
                                   "cmd.exe", "powershell.exe", "wt.exe",
                                   "taskmgr.exe", "control.exe", "mspaint.exe"}
                for exe in entry["executables"]:
                    if exe.lower() in SYSTEM_BUILTINS:
                        return exe, "system"

                # d) Last resort: bare exe name via shell (may fail if not in PATH)
                return entry["executables"][0], "system"


        # 3. Direct lookup in catalog
        with self._lock:
            if clean_key in self._catalog:
                item = self._catalog[clean_key]
                return item["target"], item["type"]

        # 4. Check system PATH
        which_path = shutil.which(norm_spoken) or shutil.which(f"{norm_spoken}.exe")
        if which_path:
            return which_path, "exe"

        # 5. RapidFuzz matching across indexed app names and aliases
        best_cand: Optional[Dict[str, Any]] = None
        best_score = 0.0

        with self._lock:
            catalog_items = list(self._catalog.values())

        for entry in catalog_items:
            app_name = entry.get("name", "")
            score1 = fuzz.token_sort_ratio(norm_spoken, app_name.lower())
            score2 = fuzz.partial_ratio(clean_key, self._normalize(app_name))
            score = max(score1, score2)

            for alias in entry.get("aliases", []):
                score_alias = fuzz.token_sort_ratio(norm_spoken, alias.lower())
                if score_alias > score:
                    score = score_alias

            if score > best_score:
                best_score = score
                best_cand = entry

        if best_cand and best_score >= 65.0:
            logger.info(f"Fuzzy matched app '{spoken_name}' -> '{best_cand['name']}' (score: {best_score:.1f})")
            return best_cand["target"], best_cand["type"]

        return None

    def activate_running_window(self, app_name: str) -> bool:
        """
        Finds and activates an existing running window of the application.
        Matches by process executable name (psutil) and fuzzy window titles.
        """
        if not HAS_WIN32:
            return False

        norm_target = speech_normalizer.replace_homophones(app_name.strip().lower())
        target_key = self._normalize(norm_target)

        # Collect process names to match
        proc_names: Set[str] = {f"{target_key}.exe", target_key}
        for key, entry in self.BUILTIN_APPS.items():
            if target_key == self._normalize(key) or any(target_key == self._normalize(a) for a in entry.get("aliases", [])):
                for p in entry.get("process_names", []):
                    proc_names.add(p.lower())

        matching_hwnds: List[Tuple[int, float]] = []

        def _enum_callback(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return True

                # 1. Process name match
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    pname = psutil.Process(pid).name().lower()
                except Exception:
                    pname = ""

                if pname in proc_names or any(p in pname for p in proc_names if len(p) >= 4):
                    matching_hwnds.append((hwnd, 100.0))
                    return True

                # 2. Window title partial/token match
                norm_title = self._normalize(title)
                score = fuzz.token_sort_ratio(norm_target, title.lower())
                partial = fuzz.partial_ratio(target_key, norm_title)
                max_score = max(score, partial)
                if max_score >= 70.0:
                    matching_hwnds.append((hwnd, max_score))

            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_enum_callback, 0)
        except Exception as e:
            logger.debug(f"EnumWindows error in activate_running_window: {e}")

        if matching_hwnds:
            # Sort by match score descending
            matching_hwnds.sort(key=lambda x: x[1], reverse=True)
            hwnd = matching_hwnds[0][0]
            try:
                # Bypass Windows foreground lock using Alt key event pulse
                import ctypes
                user32 = ctypes.windll.user32
                user32.keybd_event(0x12, 0, 0, 0)  # Alt down
                user32.keybd_event(0x12, 0, 2, 0)  # Alt up

                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                else:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

                win32gui.SetForegroundWindow(hwnd)
                return True
            except Exception as e:
                logger.debug(f"Could not bring window to foreground: {e}")

        return False

    def open_or_activate(self, app_name: str) -> str:
        """Brings the application to foreground if running, or launches it."""
        norm_name = speech_normalizer.replace_homophones(app_name.strip().lower())

        # 1. Attempt activating existing running window first
        if norm_name not in ["explorer", "file explorer", "cmd", "powershell"]:
            if self.activate_running_window(norm_name):
                return f"Switched to {app_name}."

        # 2. Resolve executable / UWP / shortcut target
        res = self.find_executable(norm_name)
        if not res:
            raise FileNotFoundError(f"I could not find an application named '{app_name}' on this PC.")

        target, app_type = res

        try:
            if app_type == "uwp":
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
            elif app_type == "lnk":
                os.startfile(target)
            elif app_type == "system":
                subprocess.Popen([target], shell=True)
            elif target.lower().endswith((".cmd", ".bat")):
                subprocess.Popen([target], shell=True)
            else:
                subprocess.Popen([target])

            return f"Opening {app_name}."
        except Exception as e:
            logger.warning(f"Direct launch error on '{target}': {e}, falling back to startfile")
            try:
                os.startfile(target)
                return f"Opening {app_name}."
            except Exception as e2:
                raise RuntimeError(f"Could not open {app_name}: {e2}")

    def close_app(self, app_name: str) -> str:
        """Finds windows matching the app name or process name and gracefully closes them."""
        # 0. If user asked to close a file or editor tab, delegate to vscode_adapter
        check_name = (app_name or "").strip().lower()
        if check_name in ["this file", "the file", "file", "current file", "active file", "file in vscode", "vscode file", "file vscode"] or re.search(r'\.[a-zA-Z0-9]{1,5}$', check_name):
            try:
                from app.editor.vscode_adapter import vscode_adapter
                return vscode_adapter.close_file(app_name if re.search(r'\.[a-zA-Z0-9]{1,5}$', check_name) else None)
            except Exception as e:
                logger.warning(f"Error redirecting close_app to close_file: {e}")

        if not HAS_WIN32:
            return f"Closed {app_name}."

        norm_name = speech_normalizer.replace_homophones(app_name.strip().lower())
        target_key = self._normalize(norm_name)
        closed_any = False

        # Gather target process names
        proc_names: Set[str] = {f"{target_key}.exe", target_key}
        for key, entry in self.BUILTIN_APPS.items():
            if target_key == self._normalize(key) or any(target_key == self._normalize(a) for a in entry.get("aliases", [])):
                for p in entry.get("process_names", []):
                    proc_names.add(p.lower())

        # 1. Native Windows graceful close via taskkill (sends WM_CLOSE to process windows)
        for p in list(proc_names):
            if p.endswith(".exe"):
                try:
                    res = subprocess.run(["taskkill", "/IM", p], capture_output=True, text=True, timeout=3.0)
                    if res.returncode == 0:
                        closed_any = True
                except Exception:
                    pass

        # 2. Window enumeration via win32gui
        def _close_callback(hwnd, _):
            nonlocal closed_any
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return True

                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    pname = psutil.Process(pid).name().lower()
                except Exception:
                    pname = ""

                # Match by process name or window title
                if pname in proc_names or target_key in self._normalize(title):
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    closed_any = True
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_close_callback, 0)
        except Exception as e:
            logger.debug(f"EnumWindows error in close_app: {e}")

        if closed_any:
            return f"Closed {app_name}."

        # 3. Fallback: check running processes without a visible window
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() in proc_names:
                    proc.terminate()
                    closed_any = True
            except Exception:
                pass

        if closed_any:
            return f"Closed {app_name}."

        return f"No open windows found for '{app_name}'."
