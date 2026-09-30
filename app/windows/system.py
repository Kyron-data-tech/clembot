import ctypes
from datetime import datetime
from pathlib import Path
from typing import Optional
import pyautogui

from app.filesystem.paths import WindowsPathResolver
from app.logging.logger import logger


class WindowsSystemControls:
    """
    Windows system utilities: volume, screenshots, and system state.
    """

    # Virtual key codes for volume control
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    @classmethod
    def _send_key(cls, vk_code: int) -> None:
        ctypes.windll.user32.keybd_event(vk_code, 0, cls.KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(vk_code, 0, cls.KEYEVENTF_EXTENDEDKEY | cls.KEYEVENTF_KEYUP, 0)

    @classmethod
    def volume_up(cls, steps: int = 5) -> str:
        """Increases volume by specified steps."""
        for _ in range(steps):
            cls._send_key(cls.VK_VOLUME_UP)
        return "Volume increased."

    @classmethod
    def volume_down(cls, steps: int = 5) -> str:
        """Decreases volume by specified steps."""
        for _ in range(steps):
            cls._send_key(cls.VK_VOLUME_DOWN)
        return "Volume decreased."

    @classmethod
    def volume_mute_toggle(cls) -> str:
        """Toggles volume mute."""
        cls._send_key(cls.VK_VOLUME_MUTE)
        return "Mute toggled."

    @classmethod
    def capture_screenshot(cls, destination_folder: Optional[Path] = None) -> tuple[Path, str]:
        """
        Captures the full screen, applies binary thresholding, compresses to
        ≤100 KB and saves to Pictures/Screenshots (or Desktop as fallback).
        Returns (saved_path, confirmation_message).
        """
        from app.windows.screen_reader import ScreenReader

        if destination_folder is None:
            standard = WindowsPathResolver.get_standard_folders()
            screenshots_dir = standard["Pictures"] / "Screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            target_dir = screenshots_dir if screenshots_dir.is_dir() else standard["Desktop"]
        else:
            target_dir = Path(destination_folder)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = target_dir / f"Screenshot_{timestamp}.png"

        try:
            data, info = ScreenReader.capture_and_compress(save_path=filepath, binary=True)
            logger.info(f"Screenshot saved: {filepath}  [{info}]")
            return filepath, f"Screenshot saved. {info}."
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            return filepath, f"Could not capture screenshot: {e}."


