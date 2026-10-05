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
    Executes an AppleScript script using /usr/bin/osascript.

    Args:
        script: AppleScript code to execute.
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
    Executes a multiline AppleScript via standard input.
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
