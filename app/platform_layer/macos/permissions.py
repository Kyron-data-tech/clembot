"""
app/platform_layer/macos/permissions.py

macOS TCC (Transparency, Consent, and Control) permission checks and user guidance.
Audits Microphone, Accessibility, Automation (Apple Events), and Screen Recording
and provides exact step-by-step remediation commands.
"""

import ctypes
import os
import subprocess
from typing import List, Tuple

from app.logging.logger import logger
from app.platform_layer.macos.applescript import run_applescript


class MacOSPermissions:
    """Detects and guides macOS Privacy & Security permissions."""

    @classmethod
    def check_microphone(cls) -> Tuple[bool, str]:
        """Checks if audio input hardware and microphone permissions are accessible."""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            count = p.get_device_count()
            p.terminate()
            if count > 0:
                return True, "Microphone accessible."
            return False, "No audio input devices detected."
        except Exception as e:
            return False, f"Microphone error: {e}"

    @classmethod
    def check_accessibility(cls) -> Tuple[bool, str]:
        """Checks if process has Accessibility permissions via AXIsProcessTrusted."""
        try:
            app_services_path = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            if os.path.exists(app_services_path):
                app_services = ctypes.cdll.LoadLibrary(app_services_path)
                is_trusted = app_services.AXIsProcessTrusted()
                if is_trusted:
                    return True, "Accessibility permission granted."
                return False, "Accessibility permission NOT granted."
        except Exception as e:
            logger.debug(f"AXIsProcessTrusted check failed: {e}")

        # Fallback check via osascript UI element inspection
        success, out = run_applescript('tell application "System Events" to return count of windows of (first application process whose frontmost is true)')
        if success:
            return True, "Accessibility permission granted."
        return False, "Accessibility permission NOT granted."

    @classmethod
    def check_automation(cls) -> Tuple[bool, str]:
        """Checks if process is allowed to send Apple Events to System Events."""
        success, out = run_applescript('tell application "System Events" to return name of current user')
        if success:
            return True, "Apple Events Automation granted."
        if "-1743" in out or "not permitted" in out.lower() or "not authorized" in out.lower():
            return False, "Apple Events Automation NOT permitted (Error -1743)."
        return False, f"Apple Events check failed: {out}"

    @classmethod
    def check_screen_recording(cls) -> Tuple[bool, str]:
        """Checks if screen recording is permitted."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        try:
            res = subprocess.run(["/usr/sbin/screencapture", "-x", tmp_path], capture_output=True, timeout=3.0)
            if res.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                return True, "Screen Recording permission granted."
            return False, "Screen Recording permission NOT granted."
        except Exception as e:
            return False, f"Screen recording check failed: {e}"
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    @classmethod
    def check_all(cls) -> List[Tuple[str, bool, str]]:
        """Runs full permission audit."""
        return [
            ("Microphone", *cls.check_microphone()),
            ("Accessibility", *cls.check_accessibility()),
            ("Automation (Apple Events)", *cls.check_automation()),
            ("Screen Recording", *cls.check_screen_recording()),
        ]

    @classmethod
    def get_permission_guidance(cls) -> str:
        """Returns clear step-by-step instructions for enabling missing permissions."""
        results = cls.check_all()
        missing = [name for name, granted, _ in results if not granted]

        if not missing:
            return "All macOS permissions are successfully granted!"

        lines = [
            "=" * 60,
            " CLEMBOT macOS PERMISSIONS SETUP",
            "=" * 60,
            "Clembot needs the following macOS permissions to function correctly:",
            "",
        ]

        for name in missing:
            lines.append(f"  [MISSING] {name}")

        lines.extend([
            "",
            "HOW TO GRANT PERMISSIONS IN macOS:",
            "1. Open System Settings -> Privacy & Security.",
            "2. For each missing permission above, click on it and toggle ON:",
            "   - Terminal (if running from Terminal / iTerm2)",
            "   - Clembot.app (if running the bundled application)",
            "   - Python (if prompted)",
            "",
            "QUICK TERMINAL SHORTCUTS TO OPEN SETTINGS:",
        ])

        if "Accessibility" in missing:
            lines.append("  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'")
        if "Microphone" in missing:
            lines.append("  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone'")
        if "Automation (Apple Events)" in missing:
            lines.append("  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation'")
        if "Screen Recording" in missing:
            lines.append("  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'")

        lines.append("=" * 60)
        return "\n".join(lines)
