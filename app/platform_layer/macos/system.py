"""
app/platform_layer/macos/system.py

macOS system controls: master output volume via AppleScript, screenshot capture
via /usr/sbin/screencapture, clipboard via pbcopy/pbpaste, and input via KeyMap & PyAutoGUI.
"""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import pyautogui
except Exception:
    pyautogui = None

from PIL import Image

from app.logging.logger import logger
from app.platform_layer.keymap import KeyMap
from app.platform_layer.macos.applescript import run_applescript, run_multiline_applescript


class MacOSSystemControls:
    """Controls volume, screenshot capture, clipboard, and input on macOS."""

    @classmethod
    def volume_up(cls, steps: int = 5) -> str:
        """Increases system output volume."""
        script = f'''
        set curVol to output volume of (get volume settings)
        set newVol to curVol + ({steps} * 3)
        if newVol > 100 then set newVol to 100
        set volume output volume newVol
        return newVol
        '''
        success, out = run_multiline_applescript(script)
        if success:
            return f"Volume increased to {out.strip()}%."
        return "Volume increased."

    @classmethod
    def volume_down(cls, steps: int = 5) -> str:
        """Decreases system output volume."""
        script = f'''
        set curVol to output volume of (get volume settings)
        set newVol to curVol - ({steps} * 3)
        if newVol < 0 then set newVol to 0
        set volume output volume newVol
        return newVol
        '''
        success, out = run_multiline_applescript(script)
        if success:
            return f"Volume decreased to {out.strip()}%."
        return "Volume decreased."

    @classmethod
    def volume_mute_toggle(cls) -> str:
        """Toggles audio mute."""
        script = '''
        set curMute to output muted of (get volume settings)
        set volume output muted (not curMute)
        return not curMute
        '''
        success, out = run_multiline_applescript(script)
        if success and "true" in out.lower():
            return "Volume muted."
        return "Volume unmuted."

    @classmethod
    def capture_screenshot(cls, destination_folder: Optional[Path] = None) -> Tuple[Path, str]:
        """
        Captures the primary macOS screen via /usr/sbin/screencapture,
        compresses image to <= 100 KB using Pillow, and returns (saved_path, status_message).
        """
        if destination_folder is None:
            pictures = Path.home() / "Pictures" / "Screenshots"
            pictures.mkdir(parents=True, exist_ok=True)
            target_dir = pictures if pictures.is_dir() else (Path.home() / "Desktop")
        else:
            target_dir = Path(destination_folder)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = target_dir / f"Screenshot_{timestamp}.png"

        try:
            # 1. Native screencapture -x (silent)
            proc = subprocess.run(
                ["/usr/sbin/screencapture", "-x", str(filepath)],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if proc.returncode != 0 or not filepath.exists():
                # Fallback to PyAutoGUI / Pillow ImageGrab
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(filepath, "PNG")

            # 2. Compress image to <= 100 KB
            size_kb = filepath.stat().st_size / 1024
            if size_kb > 100:
                with Image.open(filepath) as img:
                    # Convert to grayscale or optimize
                    img_gray = img.convert("L")
                    # Scale down if necessary
                    w, h = img_gray.size
                    if w > 1920:
                        ratio = 1920 / w
                        img_gray = img_gray.resize((1920, int(h * ratio)), Image.Resampling.LANCZOS)
                    img_gray.save(filepath, "PNG", optimize=True)

            final_kb = filepath.stat().st_size / 1024
            logger.info(f"macOS Screenshot saved: {filepath} ({final_kb:.1f} KB)")
            return filepath, f"Screenshot saved ({final_kb:.1f} KB)."
        except Exception as e:
            logger.error(f"Failed to capture macOS screenshot: {e}")
            return filepath, f"Could not capture screenshot: {e}."

    # ── Clipboard ──────────────────────────────────────────────────────────────

    @staticmethod
    def copy_text(text: str) -> str:
        """Copies text to clipboard using pbcopy."""
        try:
            proc = subprocess.Popen(["/usr/bin/pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"), timeout=2.0)
            return "Copied to clipboard."
        except Exception as e:
            logger.debug(f"pbcopy error: {e}, fallback to pyperclip")
            import pyperclip
            pyperclip.copy(text)
            return "Copied to clipboard."

    @staticmethod
    def get_text() -> str:
        """Gets text from clipboard using pbpaste."""
        try:
            proc = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True, timeout=2.0)
            return proc.stdout
        except Exception as e:
            logger.debug(f"pbpaste error: {e}, fallback to pyperclip")
            import pyperclip
            return pyperclip.paste() or ""

    @staticmethod
    def clear() -> str:
        """Clears clipboard."""
        try:
            proc = subprocess.Popen(["/usr/bin/pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(b"", timeout=2.0)
            return "Clipboard cleared."
        except Exception:
            return "Could not clear clipboard."

    # ── Keyboard & Input ───────────────────────────────────────────────────────

    @classmethod
    def send_hotkey(cls, *keys: str) -> None:
        """Maps keys (e.g. 'ctrl' -> 'command') and triggers hotkey."""
        mapped = KeyMap.map_keys(list(keys))
        if pyautogui is not None:
            try:
                pyautogui.hotkey(*mapped)
                return
            except Exception as e:
                logger.debug(f"pyautogui.hotkey failed: {e}")

        # Native AppleScript fallback for keyboard shortcuts
        mods = []
        key_char = ""
        for k in mapped:
            k_low = k.lower().strip()
            if k_low in ("command", "cmd"):
                mods.append("command down")
            elif k_low in ("shift",):
                mods.append("shift down")
            elif k_low in ("option", "alt"):
                mods.append("option down")
            elif k_low in ("control", "ctrl"):
                mods.append("control down")
            else:
                key_char = k_low

        if key_char:
            using_clause = f" using {{{', '.join(mods)}}}" if mods else ""
            run_applescript(f'tell application "System Events" to keystroke "{key_char}"{using_clause}')

    @classmethod
    def type_text(cls, text: str, interval: float = 0.01) -> None:
        """Safely types text via clipboard copy + Command+V paste."""
        if not text:
            return
        cls.copy_text(text)
        cls.send_hotkey("command", "v")

    @classmethod
    def press_key(cls, key: str) -> None:
        """Presses a single key."""
        if pyautogui is not None:
            try:
                pyautogui.press(key)
                return
            except Exception:
                pass
        run_applescript(f'tell application "System Events" to keystroke "{key}"')
