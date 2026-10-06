"""
tests/test_screen_reader.py

Unit tests for ScreenReader, binary thresholding, under-100KB compression,
system screenshot capture, and fast-router screen reading commands.
"""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from app.commands.fast_router import FastCommandRouter
from app.core.models import AgentAction
from app.windows.screen_reader import ScreenReader, MAX_BYTES, THRESHOLD
from app.windows.system import WindowsSystemControls


class TestScreenReaderProcessing(unittest.TestCase):
    """Tests image thresholding, compression, and sizing constraints."""

    def test_to_binary_static_threshold_converts_to_mode_1(self):
        """Explicit threshold= parameter keeps backward-compat static path."""
        img = Image.new("RGB", (100, 100), color=(50, 50, 50))
        for x in range(50, 100):
            for y in range(100):
                img.putpixel((x, y), (200, 200, 200))

        bin_img = ScreenReader.to_binary(img, threshold=140, blur=0.0)
        self.assertEqual(bin_img.mode, "1")

        # Dark half (<140) → black (0 / False)
        self.assertEqual(bin_img.getpixel((10, 10)), 0)
        # Light half (>=140) → white (255 / True)
        self.assertEqual(bin_img.getpixel((80, 80)), 255)

    def test_to_binary_adaptive_dark_background_detects_text(self):
        """Adaptive mode must detect all text on dark/black backgrounds."""
        import numpy as np
        from PIL import ImageDraw

        # Simulate a dark terminal: background (25,25,25), various text colors
        img = Image.new("RGB", (600, 300), color=(25, 25, 25))
        d = ImageDraw.Draw(img)
        d.text((20, 30),  "# Green comment",         fill=(106, 153, 85))   # dark green
        d.text((20, 80),  "def authenticate():",     fill=(86, 156, 214))   # dark blue keyword
        d.text((20, 130), "line_number_text",         fill=(110, 110, 110))  # dim gray
        d.text((20, 180), "Error: connection reset",  fill=(255, 100, 100))  # red error

        bin_img = ScreenReader.to_binary(img)  # uses adaptive (threshold=None)
        self.assertEqual(bin_img.mode, "1")

        arr = np.array(bin_img)
        # Each text line must have white pixels (True) detected
        self.assertGreater(arr[25:55].sum(),   50,  "Green comment not detected")
        self.assertGreater(arr[75:105].sum(),  50,  "Blue keyword not detected")
        self.assertGreater(arr[125:155].sum(), 50,  "Dim gray line numbers not detected")
        self.assertGreater(arr[175:205].sum(), 50,  "Red error text not detected")

    def test_to_binary_adaptive_light_background_detects_text(self):
        """Adaptive mode must correctly detect dark text on a white/light background."""
        import numpy as np
        from PIL import ImageDraw

        img = Image.new("RGB", (600, 200), color=(250, 250, 250))
        d = ImageDraw.Draw(img)
        d.text((20, 30), "Black text on white page",  fill=(10, 10, 10))
        d.text((20, 80), "Dark blue hyperlink",       fill=(0, 0, 200))
        d.text((20, 130), "Dark green comment",       fill=(0, 128, 0))

        bin_img = ScreenReader.to_binary(img)
        self.assertEqual(bin_img.mode, "1")

        arr = np.array(bin_img)
        # On light bg, text is black (False=0) and background is white (True=1)
        # So background pixels should be the majority
        total = arr.size
        white_ratio = arr.sum() / total
        self.assertGreater(white_ratio, 0.90, "Light background should be mostly white")
        # And there should be some black text pixels
        black_pixels = (~arr).sum()
        self.assertGreater(black_pixels, 50, "Dark text on light background not detected")

    def test_to_binary_adaptive_black_screen_has_no_artifacts(self):
        """A completely black screen should produce an all-black binary image."""
        import numpy as np

        img = Image.new("RGB", (800, 600), color=(0, 0, 0))
        bin_img = ScreenReader.to_binary(img)
        arr = np.array(bin_img)
        self.assertEqual(arr.sum(), 0, "Solid black screen should produce no white pixels")

    def test_to_binary_adaptive_dark_screen_under_100kb(self):
        """Full 1080p dark-themed screen processed adaptively must stay under 100 KB."""
        import numpy as np
        from PIL import ImageDraw

        img = Image.new("RGB", (1920, 1080), color=(30, 30, 30))
        d = ImageDraw.Draw(img)
        for i in range(40):
            y = 20 + i * 25
            d.text((20, y),  str(i + 1),                            fill=(110, 110, 110))
            d.text((80, y),  "def function_" + str(i) + "():",      fill=(220, 220, 170))
            d.text((550, y), "# comment " + str(i),                 fill=(106, 153, 85))

        bin_img = ScreenReader.to_binary(img)
        data, w, h, kb = ScreenReader.compress(bin_img, max_bytes=MAX_BYTES)
        self.assertLessEqual(len(data), MAX_BYTES, f"Exceeded 100KB: {kb:.1f} KB")

    def test_compress_strictly_under_100kb(self):
        # Synthetic high-resolution full-screen image (1920x1080)
        img = Image.new("RGB", (1920, 1080), color=(255, 255, 255))
        bin_img = ScreenReader.to_binary(img)

        data, w, h, kb = ScreenReader.compress(bin_img, max_bytes=MAX_BYTES)
        self.assertLessEqual(len(data), MAX_BYTES)
        self.assertLessEqual(kb, 100.0)

        # Verify output is a valid PNG
        loaded = Image.open(io.BytesIO(data))
        self.assertEqual(loaded.format, "PNG")

    def test_compress_high_entropy_worst_case_under_100kb(self):
        # High entropy noise image - worst-case for PNG compression
        noise = Image.effect_noise((1920, 1080), 60.0).convert("RGB")
        bin_img = ScreenReader.to_binary(noise, threshold=128)

        data, w, h, kb = ScreenReader.compress(bin_img, max_bytes=MAX_BYTES)
        self.assertLessEqual(len(data), MAX_BYTES)
        self.assertLessEqual(kb, 100.0)

    def test_capture_and_compress_saves_to_disk(self):
        mock_raw = Image.new("RGB", (800, 600), color=(100, 150, 200))
        with patch.object(ScreenReader, "capture_raw", return_value=mock_raw):
            with tempfile.TemporaryDirectory() as tmpdir:
                save_file = Path(tmpdir) / "test_screenshot.png"
                data, info = ScreenReader.capture_and_compress(save_path=save_file, binary=True)

                self.assertTrue(save_file.exists())
                file_size = save_file.stat().st_size
                self.assertLessEqual(file_size, MAX_BYTES)
                self.assertEqual(file_size, len(data))
                self.assertIn("binary thresholded", info)




class TestScreenReaderAI(unittest.TestCase):
    """Tests AI vision description and fallbacks."""

    def test_describe_with_ai_fallback_when_no_api_key(self):
        mock_raw = Image.new("RGB", (400, 300), color=(255, 255, 255))
        with patch.object(ScreenReader, "capture_raw", return_value=mock_raw):
            with patch("app.config.settings.settings.gemini_api_key", ""):
                result = ScreenReader.describe_with_ai()
                self.assertIn("Screen captured successfully", result)
                self.assertIn("configure a Gemini API key", result)

    def test_describe_with_ai_calls_gemini_vision(self):
        mock_raw = Image.new("RGB", (400, 300), color=(255, 255, 255))
        mock_response = MagicMock()
        mock_response.text = "You have Visual Studio Code open editing python code."

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch.object(ScreenReader, "capture_raw", return_value=mock_raw):
            with patch("app.config.settings.settings.gemini_api_key", "test-key-123"):
                with patch("google.genai.Client", return_value=mock_client):
                    result = ScreenReader.describe_with_ai(prompt="What is on my screen?")
                    self.assertIn("Visual Studio Code", result)

    def test_describe_with_ai_handles_capture_failure(self):
        with patch.object(ScreenReader, "capture_raw", side_effect=OSError("Display device unavailable")):
            result = ScreenReader.describe_with_ai()
            self.assertIn("Could not capture the screen", result)


class TestWindowsSystemScreenshot(unittest.TestCase):
    """Tests WindowsSystemControls.capture_screenshot integration."""

    def test_capture_screenshot_creates_under_100kb_file(self):
        mock_raw = Image.new("RGB", (1280, 720), color=(200, 200, 200))
        with patch.object(ScreenReader, "capture_raw", return_value=mock_raw):
            with tempfile.TemporaryDirectory() as tmpdir:
                path, msg = WindowsSystemControls.capture_screenshot(destination_folder=Path(tmpdir))
                self.assertTrue(path.exists())
                self.assertLessEqual(path.stat().st_size, MAX_BYTES)
                self.assertIn("Screenshot saved", msg)


class TestScreenCommandsFastRouter(unittest.TestCase):
    """Tests voice routing for screenshot and screen reading."""

    def setUp(self):
        self.router = FastCommandRouter()

    def _assert_routes(self, command: str, expected_type: str):
        plan = self.router.plan_for_command(command)
        self.assertIsNotNone(plan, f"No plan for command: {command!r}")
        self.assertTrue(len(plan.actions) > 0)
        self.assertEqual(plan.actions[0].type, expected_type, f"Wrong action for {command!r}")

    def test_screenshot_exact_matches(self):
        self._assert_routes("take a screenshot", "screenshot")
        self._assert_routes("take screenshot", "screenshot")
        self._assert_routes("screenshot", "screenshot")
        self._assert_routes("capture the screen", "screenshot")
        self._assert_routes("capture screen", "screenshot")
        self._assert_routes("capture the display", "screenshot")
        self._assert_routes("capture display", "screenshot")

    def test_screenshot_regex_matches(self):
        self._assert_routes("take a screenshot of the display", "screenshot")
        self._assert_routes("take a screenshot of the screen", "screenshot")
        self._assert_routes("capture the display", "screenshot")

    def test_screen_read_exact_matches(self):
        self._assert_routes("read the screen", "screen_read")
        self._assert_routes("read screen", "screen_read")
        self._assert_routes("whats on my screen", "screen_read")
        self._assert_routes("what is on my screen", "screen_read")
        self._assert_routes("whats on the screen", "screen_read")
        self._assert_routes("what is on the screen", "screen_read")
        self._assert_routes("describe the screen", "screen_read")
        self._assert_routes("describe the display", "screen_read")
        self._assert_routes("describe my screen", "screen_read")
        self._assert_routes("read this", "screen_read")
        self._assert_routes("analyse the screen", "screen_read")
        self._assert_routes("analyze the screen", "screen_read")

    def test_screen_read_regex_matches(self):
        self._assert_routes("what is displayed on the screen", "screen_read")
        self._assert_routes("what application is open on the screen", "screen_read")
        self._assert_routes("what do you see on the screen", "screen_read")
        self._assert_routes("read what is on the screen", "screen_read")

    def test_capture_raw_macos_screencapture_fallback(self):
        """Verifies macOS screencapture CLI fallback when ImageGrab fails on Darwin."""
        import sys
        dummy_img = Image.new("RGB", (200, 200), color="blue")

        def fake_screencapture(cmd, capture_output=True, timeout=5.0):
            target_path = cmd[2]
            dummy_img.save(target_path, "PNG")
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            return mock_proc

        with patch("PIL.ImageGrab.grab", side_effect=OSError("Display capture error")), \
             patch("sys.platform", "darwin"), \
             patch("subprocess.run", side_effect=fake_screencapture):
            captured = ScreenReader.capture_raw()
            self.assertEqual(captured.size, (200, 200))


if __name__ == "__main__":
    unittest.main()
