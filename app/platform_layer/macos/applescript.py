"""
app/platform_layer/macos/applescript.py

Safe, robust utility to execute AppleScript commands and scripts via /usr/bin/osascript.
Includes timeout handling, error code extraction, and string escaping.
"""

import subprocess
from typing import Tuple

from app.logging.logger import logger


def run_applescript(script: str, timeout: float = 5.0) -> Tuple[bool, str]:
    """
    Executes an AppleScript one-liner using /usr/bin/osascript -e.

    Args:
        script: AppleScript code to execute (single line or short block).
        timeout: Maximum execution time in seconds.

    Returns:
        (success: bool, output: str)
    """
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode == 0:
            return True, stdout
        else:
            logger.debug(f"AppleScript error (code {proc.returncode}): {stderr}")
            return False, stderr
    except subprocess.TimeoutExpired:
        logger.warning(f"AppleScript execution timed out after {timeout}s")
        return False, f"AppleScript timed out after {timeout}s"
    except FileNotFoundError:
        # Not on macOS or osascript is missing
        logger.warning("osascript binary not found")
        return False, "osascript not found"
    except Exception as e:
        logger.error(f"Unexpected AppleScript execution error: {e}")
        return False, str(e)


def run_multiline_applescript(script: str, timeout: float = 8.0) -> Tuple[bool, str]:
    """
    Executes a multiline AppleScript via stdin (safer than -e for multi-line scripts).
    Preferred over run_applescript for anything spanning more than one line.
    """
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript"],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode == 0:
            return True, stdout
        else:
            logger.debug(f"Multiline AppleScript error (code {proc.returncode}): {stderr}")
            return False, stderr
    except subprocess.TimeoutExpired:
        logger.warning(f"AppleScript execution timed out after {timeout}s")
        return False, f"AppleScript timed out after {timeout}s"
    except FileNotFoundError:
        logger.warning("osascript binary not found")
        return False, "osascript not found"
    except Exception as e:
        logger.error(f"Unexpected AppleScript execution error: {e}")
        return False, str(e)


def is_app_running(app_name: str) -> bool:
    """
    Checks whether an application is currently running by querying System Events.
    More reliable than 'application X is running' which can hang if the app is
    in a sandboxed state.
    """
    script = f'''
    tell application "System Events"
        return (count of (every process whose name is "{app_name}")) > 0
    end tell
    '''
    success, out = run_multiline_applescript(script, timeout=3.0)
    return success and out.strip().lower() == "true"


def get_app_window_count(app_name: str) -> int:
    """Returns the number of open windows for the given application process."""
    script = f'''
    tell application "System Events"
        if (count of (every process whose name is "{app_name}")) > 0 then
            return count of windows of first process whose name is "{app_name}"
        end if
        return 0
    end tell
    '''
    success, out = run_multiline_applescript(script, timeout=3.0)
    if success and out.strip().isdigit():
        return int(out.strip())
    return 0
