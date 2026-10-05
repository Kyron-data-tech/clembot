"""
app/platform_layer/macos/apps.py

macOS application management for Clembot.
Resolves applications using Spotlight (mdfind), standard /Applications directories,
and fuzzy matching, and controls them via 'open -a' and AppleScript.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import psutil
from rapidfuzz import fuzz

from app.logging.logger import logger
from app.platform_layer.macos.applescript import run_applescript
try:
    from app.speech.normalizer import speech_normalizer
except Exception:
    speech_normalizer = None


def _clean_spoken_name(text: str) -> str:
    clean = text.strip().lower()
    if speech_normalizer is not None:
        try:
            return speech_normalizer.replace_homophones(clean)
        except Exception:
            pass
    return clean


class MacOSAppCatalog:
    """Locates, launches, activates, and terminates macOS applications."""

    BUILTIN_APPS: Dict[str, Dict[str, Any]] = {
        "vscode": {
            "canonical": "Visual Studio Code",
            "app_name": "Visual Studio Code",
            "aliases": ["vs code", "vscode", "code", "visual studio code"],
            "bundle_id": "com.microsoft.VSCode",
            "executables": ["code"],
        },
        "chrome": {
            "canonical": "Google Chrome",
            "app_name": "Google Chrome",
            "aliases": ["chrome", "google chrome", "browser"],
            "bundle_id": "com.google.Chrome",
            "executables": ["Google Chrome"],
        },
        "brave": {
            "canonical": "Brave Browser",
            "app_name": "Brave Browser",
            "aliases": ["brave", "brave browser"],
            "bundle_id": "com.brave.Browser",
            "executables": ["Brave Browser"],
        },
        "safari": {
            "canonical": "Safari",
            "app_name": "Safari",
            "aliases": ["safari", "apple browser"],
            "bundle_id": "com.apple.Safari",
            "executables": ["Safari"],
        },
        "finder": {
            "canonical": "Finder",
            "app_name": "Finder",
            "aliases": ["finder", "files", "file manager"],
            "bundle_id": "com.apple.finder",
            "executables": ["Finder"],
        },
        "terminal": {
            "canonical": "Terminal",
            "app_name": "Terminal",
            "aliases": ["terminal", "iterm", "command prompt", "cmd", "console"],
            "bundle_id": "com.apple.Terminal",
            "executables": ["Terminal"],
        },
        "calculator": {
            "canonical": "Calculator",
            "app_name": "Calculator",
            "aliases": ["calculator", "calc"],
            "bundle_id": "com.apple.calculator",
            "executables": ["Calculator"],
        },
        "notes": {
            "canonical": "Notes",
            "app_name": "Notes",
            "aliases": ["notes", "apple notes", "notepad", "note pad"],
            "bundle_id": "com.apple.Notes",
            "executables": ["Notes"],
        },
        "settings": {
            "canonical": "System Settings",
            "app_name": "System Settings",
            "aliases": ["system settings", "settings", "system preferences", "preferences", "control panel"],
            "bundle_id": "com.apple.systempreferences",
            "executables": ["System Settings", "System Preferences"],
        },
        "activity monitor": {
            "canonical": "Activity Monitor",
            "app_name": "Activity Monitor",
            "aliases": ["activity monitor", "task manager", "taskmgr", "task mgr", "processes"],
            "bundle_id": "com.apple.ActivityMonitor",
            "executables": ["Activity Monitor"],
        },
        "spotify": {
            "canonical": "Spotify",
            "app_name": "Spotify",
            "aliases": ["spotify", "music player"],
            "bundle_id": "com.spotify.client",
            "executables": ["Spotify"],
        },
        "slack": {
            "canonical": "Slack",
            "app_name": "Slack",
            "aliases": ["slack"],
            "bundle_id": "com.tinyspeck.slackmacgap",
            "executables": ["Slack"],
        },
        "discord": {
            "canonical": "Discord",
            "app_name": "Discord",
            "aliases": ["discord"],
            "bundle_id": "com.hnc.Discord",
            "executables": ["Discord"],
        },
        "pycharm": {
            "canonical": "PyCharm",
            "app_name": "PyCharm",
            "aliases": ["pycharm", "pi charm", "pie charm"],
            "bundle_id": "com.jetbrains.pycharm",
            "executables": ["pycharm"],
        },
        "messages": {
            "canonical": "Messages",
            "app_name": "Messages",
            "aliases": ["messages", "imessage", "texts"],
            "bundle_id": "com.apple.MobileSMS",
            "executables": ["Messages"],
        },
        "mail": {
            "canonical": "Mail",
            "app_name": "Mail",
            "aliases": ["mail", "apple mail", "email"],
            "bundle_id": "com.apple.mail",
            "executables": ["Mail"],
        },
    }

    APP_DIRECTORIES = [
        Path("/Applications"),
        Path("/System/Applications"),
        Path("/System/Applications/Utilities"),
        Path.home() / "Applications",
    ]

    def __init__(self):
        self._cached_apps: Dict[str, Path] = {}
        self._scan_standard_directories()

    def _normalize(self, text: str) -> str:
        return re.sub(r'[^a-zA-Z0-9]', '', text.lower())

    def _scan_standard_directories(self) -> None:
        """Scans standard macOS application bundles to populate the lookup cache."""
        for d in self.APP_DIRECTORIES:
            if not d.is_dir():
                continue
            try:
                for item in d.glob("*.app"):
                    norm_stem = self._normalize(item.stem)
                    self._cached_apps[norm_stem] = item
            except Exception as e:
                logger.debug(f"Error scanning app dir {d}: {e}")

    def find_app_bundle(self, query: str) -> Optional[Tuple[str, Path]]:
        """
        Locates an application bundle (.app) by name or alias.
        Returns (canonical_name, path_to_app_bundle) if found.
        """
        clean_q = _clean_spoken_name(query)
        norm_q = self._normalize(clean_q)

        # 1. Built-in catalog check
        for key, entry in self.BUILTIN_APPS.items():
            if norm_q == self._normalize(key) or any(norm_q == self._normalize(a) for a in entry.get("aliases", [])):
                canonical = entry["canonical"]
                # Try cached direct path
                for path in self._cached_apps.values():
                    if path.stem.lower() == entry["app_name"].lower():
                        return canonical, path
                # Try default /Applications/<App>.app
                for d in self.APP_DIRECTORIES:
                    cand = d / f"{entry['app_name']}.app"
                    if cand.is_dir():
                        return canonical, cand
                return canonical, Path(f"/Applications/{entry['app_name']}.app")

        # 2. Direct match in cached scan
        if norm_q in self._cached_apps:
            p = self._cached_apps[norm_q]
            return p.stem, p

        # 3. Spotlight search via mdfind
        try:
            mdfind_proc = subprocess.run(
                ["/usr/bin/mdfind", f"kMDItemContentType == 'com.apple.application-bundle' && kMDItemFSName == '*{clean_q}*.app'c"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if mdfind_proc.returncode == 0 and mdfind_proc.stdout.strip():
                lines = [line.strip() for line in mdfind_proc.stdout.splitlines() if line.strip().endswith(".app")]
                if lines:
                    best_match = Path(lines[0])
                    return best_match.stem, best_match
        except Exception as e:
            logger.debug(f"mdfind lookup skipped: {e}")

        # 4. Fuzzy match across scanned app bundles
        best_cand: Optional[Path] = None
        best_score = 0.0

        for norm_name, app_path in self._cached_apps.items():
            score = max(
                fuzz.token_sort_ratio(clean_q, app_path.stem.lower()),
                fuzz.partial_ratio(norm_q, norm_name),
            )
            if score > best_score:
                best_score = score
                best_cand = app_path

        if best_cand and best_score >= 65.0:
            logger.info(f"Fuzzy matched macOS app '{query}' -> '{best_cand.stem}' (score: {best_score:.1f})")
            return best_cand.stem, best_cand

        return None

    def is_app_running(self, app_name: str) -> bool:
        """Checks if the application is currently running."""
        clean = _clean_spoken_name(app_name)
        norm = self._normalize(clean)

        # AppleScript check
        res, out = run_applescript(f'application "{clean}" is running')
        if res and out.strip() == "true":
            return True

        # Process check via psutil
        try:
            for p in psutil.process_iter(["name"]):
                pname = (p.info.get("name") or "").lower()
                if norm in self._normalize(pname):
                    return True
        except Exception:
            pass

        return False

    def activate_running_window(self, app_name: str) -> bool:
        """Brings an application to the foreground using AppleScript."""
        res = self.find_app_bundle(app_name)
        target_name = res[0] if res else app_name
        success, _ = run_applescript(f'tell application "{target_name}" to activate')
        return success

    def open_or_activate(self, app_name: str) -> str:
        """Launches or focuses the macOS application."""
        clean_name = _clean_spoken_name(app_name)
        app_info = self.find_app_bundle(clean_name)

        target = app_info[0] if app_info else app_name

        try:
            # Use /usr/bin/open -a "<App>"
            proc = subprocess.run(
                ["/usr/bin/open", "-a", target],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if proc.returncode == 0:
                return f"Opening {target}."
            else:
                # Try by path if we found one
                if app_info and app_info[1].exists():
                    subprocess.Popen(["/usr/bin/open", str(app_info[1])])
                    return f"Opening {target}."
                raise RuntimeError(f"Could not open {target}: {proc.stderr.strip()}")
        except Exception as e:
            logger.warning(f"Error opening app '{target}': {e}")
            raise RuntimeError(f"Could not open {target}: {e}")

    def close_app(self, app_name: str) -> str:
        """Gracefully quits the requested macOS application."""
        # Check if closing a file
        check = app_name.strip().lower()
        if check in ["this file", "the file", "file", "current file", "active file"] or re.search(r'\.[a-zA-Z0-9]{1,5}$', check):
            try:
                from app.editor.vscode_adapter import vscode_adapter
                return vscode_adapter.close_file(app_name if re.search(r'\.[a-zA-Z0-9]{1,5}$', check) else None)
            except Exception as e:
                logger.warning(f"Error redirecting close_app to close_file: {e}")

        res = self.find_app_bundle(app_name)
        target = res[0] if res else app_name

        success, _ = run_applescript(f'tell application "{target}" to quit')
        if success:
            return f"Closed {target}."

        # Fallback to pkill if not responding
        try:
            subprocess.run(["pkill", "-f", target], check=False)
            return f"Closed {target}."
        except Exception:
            return f"Closed {target}."
