import os
import re
from pathlib import Path
try:
    import win32api
except ImportError:
    win32api = None

from app.logging.logger import logger


class WindowsPathResolver:
    """
    Dynamically resolves Windows known folders, system drives, and relative folder names
    without hardcoding usernames or static drive letters.
    """

    FOLDER_ALIASES: Dict[str, str] = {
        "desktop": "Desktop",
        "my desktop": "Desktop",
        "documents": "Documents",
        "my documents": "Documents",
        "my documents folder": "Documents",
        "downloads": "Downloads",
        "my downloads": "Downloads",
        "my downloads folder": "Downloads",
        "pictures": "Pictures",
        "my pictures": "Pictures",
        "photos": "Pictures",
        "videos": "Videos",
        "my videos": "Videos",
        "movies": "Videos",
        "music": "Music",
        "my music": "Music",
        "home": "Home",
        "user profile": "Home",
        "onedrive": "OneDrive",
        "my onedrive": "OneDrive",
        "c drive": "C:\\",
        "drive c": "C:\\",
        "c:": "C:\\",
        "root": "C:\\",
    }

    @classmethod
    def get_user_home(cls) -> Path:
        """Returns current user's profile directory (%USERPROFILE%)."""
        user_profile = os.environ.get("USERPROFILE")
        if user_profile and os.path.isdir(user_profile):
            return Path(user_profile)
        return Path.home()

    @classmethod
    def get_standard_folders(cls) -> Dict[str, Path]:
        """Maps canonical folder names to their resolved Path on the current Windows machine."""
        home = cls.get_user_home()
        folders = {
            "Home": home,
            "Desktop": home / "Desktop",
            "Documents": home / "Documents",
            "Downloads": home / "Downloads",
            "Pictures": home / "Pictures",
            "Videos": home / "Videos",
            "Music": home / "Music",
        }

        # Check OneDrive path if configured
        onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or os.environ.get("OneDriveCommercial")
        if onedrive and os.path.isdir(onedrive):
            folders["OneDrive"] = Path(onedrive)
        elif (home / "OneDrive").is_dir():
            folders["OneDrive"] = home / "OneDrive"

        return folders

    @classmethod
    def get_available_drives(cls) -> List[str]:
        """Returns a list of all mounted drive letters (e.g. ['C:\\', 'D:\\'])."""
        drives = []
        try:
            if win32api is not None:
                bitmask = win32api.GetLogicalDrives()
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    if bitmask & 1:
                        drives.append(f"{letter}:\\")
                    bitmask >>= 1
        except Exception as e:
            logger.debug(f"win32api GetLogicalDrives failed, fallback to drive check: {e}")
            for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                drive_path = f"{letter}:\\"
                if os.path.exists(drive_path):
                    drives.append(drive_path)
        return drives

    @classmethod
    def get_active_explorer_path(cls) -> Optional[Path]:
        """
        Queries Windows File Explorer via COM to find the folder path currently open
        in the focused Explorer window.
        """
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()

            shell = win32com.client.Dispatch("Shell.Application")
            windows = shell.Windows()

            # The focused window may be an explorer window
            import win32gui
            foreground_hwnd = win32gui.GetForegroundWindow()

            for window in windows:
                try:
                    if window.HWND == foreground_hwnd or foreground_hwnd == 0:
                        location_url = window.LocationURL
                        if location_url and location_url.startswith("file:///"):
                            raw_path = location_url[8:].replace("/", "\\")
                            # Handle URL-encoded characters like %20
                            from urllib.parse import unquote
                            unquoted_path = unquote(raw_path)
                            if os.path.isdir(unquoted_path):
                                return Path(unquoted_path)
                except Exception:
                    continue

            # If foreground window was not an Explorer window, return top explorer window if any
            for window in windows:
                try:
                    location_url = window.LocationURL
                    if location_url and location_url.startswith("file:///"):
                        from urllib.parse import unquote
                        unquoted_path = unquote(location_url[8:].replace("/", "\\"))
                        if os.path.isdir(unquoted_path):
                            return Path(unquoted_path)
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Could not retrieve active File Explorer path: {e}")
        return None

    @classmethod
    def resolve_spoken_path(cls, raw: str, base_context: Optional[Path] = None, context_base: Optional[Path] = None) -> Optional[Path]:
        r"""
        Intelligently resolves space-separated spoken path representations (STT output)
        to absolute Paths on Windows.
        Examples:
        - "c users amrat desktop practice python" -> C:\Users\amrat\Desktop\practice\python
        - "c drive users amrat desktop practice python folder" -> C:\Users\amrat\Desktop\practice\python
        - "desktop practice python" -> C:\Users\amrat\Desktop\practice\python
        - "c users amrat desktop practice python practical main.py" -> C:\Users\amrat\Desktop\practice\python\practical\main.py
        - "c users amrat desktop practice python practical main py" -> C:\Users\amrat\Desktop\practice\python\practical\main.py
        """
        raw_clean = raw.strip()
        clean = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', raw_clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r'\s+(?:folder|directory|project|workspace|file)$', '', clean, flags=re.IGNORECASE).strip() or raw_clean
        clean = clean.strip("'\" ")
        if not clean:
            return None

        # 1. Direct path check
        try:
            p = Path(clean)
            if p.is_absolute() and p.exists():
                return p
        except Exception:
            pass

        # 2. Candidate roots and remaining string
        candidate_roots: List[Tuple[Path, str]] = []

        # Drive pattern: e.g. "c users amrat desktop practice python"
        # "c drive users amrat...", "drive c users amrat..."
        drive_match = re.match(r'^(?:drive\s+)?([a-zA-Z])(?::|\s+drive\b)?(?:\s*\\|\s*\/)?(?:\s+(.*))?$', clean, re.IGNORECASE)
        if drive_match:
            letter = drive_match.group(1).upper()
            d_path = Path(f"{letter}:\\")
            if d_path.exists():
                candidate_roots.append((d_path, (drive_match.group(2) or "").strip()))

        # "users <username> ..." or "c users <misheard_username> desktop..."
        # Handle cases where username was misheard by STT (e.g. android, camera, amrit, am rat)
        u_match = re.search(r'\busers\s+(.*?)\s+(desktop|downloads|documents|pictures|videos|music|onedrive)\b', clean, re.IGNORECASE)
        if u_match:
            rest_idx = u_match.start(2)
            remaining = clean[rest_idx:]
            home = cls.get_user_home()
            if home.exists():
                candidate_roots.append((home, remaining))

        # "users <username> ..."
        users_match = re.match(r'^users\s+([^\s\\]+)(?:\s+(.*))?$', clean, re.IGNORECASE)
        if users_match:
            u_name = users_match.group(1)
            u_rest = (users_match.group(2) or "").strip()
            cand_user = Path("C:\\Users") / u_name
            if cand_user.exists():
                candidate_roots.append((cand_user, u_rest))
            else:
                home = cls.get_user_home()
                if home.exists():
                    candidate_roots.append((home, u_rest))

        # Standard folder alias at start
        std_match = re.match(r'^(desktop|downloads|documents|pictures|videos|music|onedrive)(?:\s+(.*))?$', clean, re.IGNORECASE)
        if std_match:
            f_key = std_match.group(1).capitalize()
            standard = cls.get_standard_folders()
            if f_key in standard and standard[f_key].exists():
                candidate_roots.append((standard[f_key], (std_match.group(2) or "").strip()))

        # Context base / active base
        active_base = base_context or context_base
        if active_base and active_base.is_dir():
            candidate_roots.append((active_base, clean))

        # Check VS Code workspace roots
        try:
            from app.editor.vscode_adapter import VSCodeAdapter
            for ws_root in VSCodeAdapter().get_workspace_roots():
                if ws_root and ws_root.is_dir():
                    candidate_roots.append((ws_root, clean))
        except Exception:
            pass

        # Home folder
        home = cls.get_user_home()
        if home.exists():
            candidate_roots.append((home, clean))

        # Standard folders
        standard = cls.get_standard_folders()
        for sf_key in ["Desktop", "Downloads", "Documents"]:
            if sf_key in standard and standard[sf_key].exists():
                candidate_roots.append((standard[sf_key], clean))

        # Common file extensions for spoken dot handling
        common_exts = {
            "py", "txt", "json", "md", "js", "ts", "html", "css", "c", "cpp",
            "h", "cs", "java", "rs", "go", "bat", "ps1", "sh", "yaml", "yml", "xml", "csv", "pdf"
        }

        seen_roots = set()
        for root, rest in candidate_roots:
            key = (str(root).lower(), rest.lower())
            if key in seen_roots:
                continue
            seen_roots.add(key)

            if not rest:
                return root

            tokens = rest.split()
            if not tokens:
                return root

            # Check direct join
            direct = root.joinpath(*tokens)
            if direct.exists():
                return direct

            # Check spoken extension on last tokens: e.g. ["main", "py"] -> "main.py"
            if len(tokens) >= 2 and tokens[-1].lower() in common_exts:
                cand_ext = root.joinpath(*tokens[:-2], f"{tokens[-2]}.{tokens[-1].lower()}")
                if cand_ext.exists():
                    return cand_ext

            # Check spoken "dot" extension: e.g. ["main", "dot", "py"] -> "main.py"
            if len(tokens) >= 3 and tokens[-2].lower() == "dot" and tokens[-1].lower() in common_exts:
                cand_ext = root.joinpath(*tokens[:-3], f"{tokens[-3]}.{tokens[-1].lower()}")
                if cand_ext.exists():
                    return cand_ext

            # Greedy directory walk
            curr = root
            curr_tokens = list(tokens)
            failed = False

            while curr_tokens:
                matched_step = False
                for k in range(len(curr_tokens), 0, -1):
                    seg = " ".join(curr_tokens[:k])
                    direct_step = curr / seg
                    if direct_step.exists():
                        curr = direct_step
                        curr_tokens = curr_tokens[k:]
                        matched_step = True
                        break

                    if curr.is_dir():
                        try:
                            for child in curr.iterdir():
                                c_lower = child.name.lower()
                                s_lower = seg.lower()
                                if c_lower == s_lower:
                                    curr = child
                                    curr_tokens = curr_tokens[k:]
                                    matched_step = True
                                    break
                                if child.is_file():
                                    ext = child.suffix.lstrip('.').lower()
                                    if s_lower == f"{child.stem.lower()} {ext}" or s_lower == f"{child.stem.lower()} dot {ext}":
                                        curr = child
                                        curr_tokens = curr_tokens[k:]
                                        matched_step = True
                                        break
                            if matched_step:
                                break
                        except (PermissionError, OSError):
                            pass
                if not matched_step:
                    failed = True
                    break

            if not failed and curr.exists() and curr != root:
                return curr

        return None

    @classmethod
    def resolve_path(cls, raw: str, base_context: Optional[Path] = None, context_base: Optional[Path] = None) -> Path:
        r"""
        Intelligently resolves a user-spoken string or relative path to an absolute Path.
        Examples:
        - "Downloads" -> C:\Users\Username\Downloads
        - "Projects on Desktop" -> C:\Users\Username\Desktop\Projects
        - "notes.txt" -> base_context / notes.txt (or Desktop / notes.txt)
        - "C:\temp\file.txt" -> C:\temp\file.txt
        """
        active_base = base_context or context_base
        raw_clean = raw.strip()
        lower = raw_clean.lower()
        clean_target = re.sub(r'^(?:(?:the|my)\s+)?(?:file|folder|directory|project|workspace)\s+', '', raw_clean, flags=re.IGNORECASE).strip() or raw_clean

        standard_folders = cls.get_standard_folders()

        # Direct match with standard folders
        if lower in cls.FOLDER_ALIASES:
            canonical = cls.FOLDER_ALIASES[lower]
            if canonical in standard_folders:
                return standard_folders[canonical]
            if canonical.endswith(":\\") and os.path.exists(canonical):
                return Path(canonical)

        # Match phrases like "Projects on Desktop" or "resume in Downloads"
        loc_match = re.search(r'^(.*?)\s+(?:on|in|under|inside)\s+(desktop|downloads|documents|pictures|videos|music|onedrive)$', lower)
        if loc_match:
            subpath = loc_match.group(1).strip()
            loc_name = loc_match.group(2).strip()
            canonical_loc = cls.FOLDER_ALIASES.get(loc_name, "Desktop")
            parent_dir = standard_folders.get(canonical_loc, standard_folders["Desktop"])
            return parent_dir / subpath

        # Expand Windows environment variables (e.g. %USERPROFILE%\foo, %APPDATA%)
        expanded = os.path.expandvars(raw_clean)

        # Direct absolute path
        p = Path(expanded.strip("'\" "))
        if p.is_absolute():
            if p.exists():
                return p
            no_suffix = re.sub(r'\s+(?:folder|directory|project|workspace|file)$', '', str(p), flags=re.IGNORECASE).strip()
            p_no_suffix = Path(no_suffix)
            if p_no_suffix.exists():
                return p_no_suffix
            return p

        # Check spoken path resolution (e.g. "c users amrat desktop practice python")
        spoken_p = cls.resolve_spoken_path(clean_target, base_context=active_base)
        if spoken_p and spoken_p.exists():
            return spoken_p

        # If user refers to "here" or "this folder", use active Explorer path or base_context
        if lower in ["here", "this folder", "current folder"]:
            explorer_path = cls.get_active_explorer_path()
            if explorer_path:
                return explorer_path
            if active_base:
                return active_base
            return standard_folders["Desktop"]

        # If base context is provided (e.g. from conversational memory), use it if item exists there
        if active_base and active_base.is_dir():
            cand = active_base / raw_clean
            if cand.exists():
                return cand
            cand_clean = active_base / clean_target
            if cand_clean.exists():
                return cand_clean

        # Check active VS Code workspace and active file context
        try:
            from app.editor.vscode_adapter import VSCodeAdapter
            ws_match = VSCodeAdapter().find_in_workspace(clean_target)
            if ws_match and ws_match.exists():
                return ws_match
        except Exception as e:
            logger.debug(f"VS Code workspace resolution skipped: {e}")

        # Check active Explorer window if item exists there
        explorer_path = cls.get_active_explorer_path()
        if explorer_path and explorer_path.is_dir():
            cand = explorer_path / raw_clean
            if cand.exists():
                return cand
            cand_clean = explorer_path / clean_target
            if cand_clean.exists():
                return cand_clean

        # Check standard user locations if file exists there
        for folder_key in ["Desktop", "Downloads", "Documents"]:
            if folder_key in standard_folders:
                cand = standard_folders[folder_key] / raw_clean
                if cand.exists():
                    return cand
                cand_clean = standard_folders[folder_key] / clean_target
                if cand_clean.exists():
                    return cand_clean

        # Default fallback: active_base / raw_clean (or Desktop / raw_clean)
        if active_base and active_base.is_dir():
            return active_base / raw_clean
        return standard_folders["Desktop"] / raw_clean

    resolve = resolve_path
