"""
app/windows/screen_reader.py

Screen capture, binary-thresholding, size compression, and AI-powered
visual description for Clembot's "read the screen" feature.

Pipeline
────────
  1. Capture full screen with PIL ImageGrab
  2. Convert to grayscale (removes colour noise)
  3. Apply Gaussian blur  (smooths salt-and-pepper noise before threshold)
  4. Binary threshold     (every pixel → pure black or pure white)
  5. Compress to PNG, scaling down in steps until ≤ 100 KB
  6. Optionally send the compact image to Gemini Vision for OCR/description
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter, ImageGrab

from app.logging.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_BYTES = 100 * 1024          # 100 KB hard limit
THRESHOLD = 140                 # Grayscale cut-off (0–255).  Higher → more white.
BLUR_RADIUS = 0.8               # Pre-threshold Gaussian blur (reduces noise)
_SCALE_STEPS = [1.0, 0.75, 0.5, 0.35, 0.25, 0.18]  # Progressive downscale


class ScreenReader:
    """
    Captures the Windows desktop, produces a compact binary-thresholded
    PNG image (≤100 KB), and optionally asks an AI model to describe or
    read the visible content aloud.
    """

    # ── 1. Capture ────────────────────────────────────────────────────────────

    @staticmethod
    def capture_raw() -> Image.Image:
        """Full-screen capture in full colour (RGB)."""
        return ImageGrab.grab(all_screens=False)   # primary monitor only

    # ── 2. Binary thresholding ────────────────────────────────────────────────

    @staticmethod
    def to_binary(
        img: Image.Image,
        threshold: Optional[int] = None,
        blur: float = BLUR_RADIUS,
        adaptive_radius: int = 15,
        c_dark: int = 10,
        c_light: int = 12,
    ) -> Image.Image:
        """
        Convert image to a high-contrast binary (black/white) version.

        When `threshold` is None (default):
          Uses adaptive local background thresholding. Detects whether the local
          background is dark (e.g. terminal, dark theme code editor, dark window)
          or light (e.g. browser, white document). In dark areas, text (including
          syntax highlighting, comments, line numbers, dim colors) is crisply
          separated and converted to pure white (255) on pure black (0). In light
          areas, text is converted to pure black (0) on pure white (255).

        When `threshold` is specified:
          Uses static global thresholding for backward compatibility.
        """
        gray = img.convert("L")

        # Explicit static threshold mode (for backward compatibility / explicit callers)
        if threshold is not None:
            if blur > 0:
                gray = gray.filter(ImageFilter.GaussianBlur(radius=blur))
            binary_l = gray.point(lambda p: 255 if p >= threshold else 0, mode="L")
            return binary_l.convert("1")

        # Smart Adaptive Local Thresholding
        local_bg = gray.filter(ImageFilter.BoxBlur(adaptive_radius))

        g = np.array(gray, dtype=np.int16)
        b = np.array(local_bg, dtype=np.int16)

        is_dark_bg = b < 128

        # Dark background (terminal / dark IDE / dark theme):
        # Text is brighter than local background by at least c_dark
        dark_text = (g >= (b + c_dark))

        # Light background (browser / document / light theme):
        # Text is darker than local background by at least c_light
        light_text = (g <= (b - c_light))

        out = np.zeros_like(g, dtype=np.uint8)
        # In dark regions: text is 255 (white), background is 0 (black)
        out[is_dark_bg & dark_text] = 255
        out[is_dark_bg & (~dark_text)] = 0
        # In light regions: text is 0 (black), background is 255 (white)
        out[(~is_dark_bg) & light_text] = 0
        out[(~is_dark_bg) & (~light_text)] = 255

        return Image.fromarray(out, mode="L").convert("1")

    # ── 3. Compress to ≤100 KB ────────────────────────────────────────────────

    @classmethod
    def compress(
        cls,
        img: Image.Image,
        max_bytes: int = MAX_BYTES,
    ) -> Tuple[bytes, int, int, float]:
        """
        Encode `img` to PNG, progressively downscaling until ≤ max_bytes.

        Returns (png_bytes, width, height, size_kb).
        """
        orig_w, orig_h = img.size
        is_mode_1 = (img.mode == "1")

        for scale in _SCALE_STEPS:
            nw = max(1, int(orig_w * scale))
            nh = max(1, int(orig_h * scale))

            if scale == 1.0:
                candidate = img
            else:
                inter = img.convert("L") if is_mode_1 else img
                resized = inter.resize((nw, nh), Image.LANCZOS)
                candidate = (
                    resized.point(lambda p: 255 if p > 127 else 0, mode="1")
                    if is_mode_1
                    else resized
                )

            with io.BytesIO() as buf:
                candidate.save(buf, format="PNG", optimize=True, compress_level=9)
                data = buf.getvalue()

            if len(data) <= max_bytes:
                return data, nw, nh, len(data) / 1024

        # Absolute last resort: JPEG 4:1 downscale at low quality
        logger.warning("ScreenReader: PNG path failed to reach 100 KB; falling back to JPEG")
        data = b""
        for quality in [60, 40, 20, 10]:
            nw, nh = max(1, int(orig_w * 0.18)), max(1, int(orig_h * 0.18))
            rgb = img.convert("RGB").resize((nw, nh), Image.LANCZOS)
            with io.BytesIO() as buf:
                rgb.save(buf, format="JPEG", quality=quality, optimize=True)
                data = buf.getvalue()
            if len(data) <= max_bytes:
                return data, nw, nh, len(data) / 1024

        return data, nw, nh, len(data) / 1024   # best effort

    # ── 4. Full pipeline ──────────────────────────────────────────────────────

    @classmethod
    def capture_and_compress(
        cls,
        save_path: Optional[Path] = None,
        threshold: Optional[int] = None,
        blur: float = BLUR_RADIUS,
        binary: bool = True,
    ) -> Tuple[bytes, str]:
        """
        End-to-end pipeline:
          capture → (optional adaptive binary) → compress → optional save

        Returns:
          (image_bytes, human_readable_info)
        """
        raw = cls.capture_raw()
        img = cls.to_binary(raw, threshold=threshold, blur=blur) if binary else raw
        data, w, h, kb = cls.compress(img)

        if save_path:
            Path(save_path).write_bytes(data)
            logger.info(f"ScreenReader: saved {kb:.1f} KB binary screenshot → {save_path}")

        info = f"{w}×{h} px, {kb:.1f} KB (binary thresholded)"
        return data, info

    # ── 5. AI Vision description ──────────────────────────────────────────────

    # Cached Gemini client — recreated only when the API key changes
    _gemini_client = None
    _gemini_client_key: Optional[str] = None

    @classmethod
    def _get_gemini_client(cls):
        """Returns a cached Gemini client, rebuilding if the API key changed."""
        from app.config.settings import settings
        from google import genai
        from google.genai import types as gtypes

        key = settings.gemini_api_key
        if cls._gemini_client is None or cls._gemini_client_key != key:
            cls._gemini_client = genai.Client(
                api_key=key,
                http_options=gtypes.HttpOptions(timeout=15_000),  # 15 s timeout
            )
            cls._gemini_client_key = key
        return cls._gemini_client

    @classmethod
    def describe_with_ai(
        cls,
        prompt: str = "What is displayed on this screen? Describe it briefly and clearly.",
        threshold: Optional[int] = None,
        blur: float = BLUR_RADIUS,
    ) -> str:
        """
        Capture the screen → binary image → send to Gemini Vision.
        Returns a spoken description string (1-3 sentences, no markdown).

        Falls back gracefully if Gemini is unavailable.
        """
        from app.config.settings import settings

        # ── a) Capture the compact binary image ──────────────────────────────
        try:
            raw = cls.capture_raw()
        except Exception as e:
            logger.error(f"ScreenReader capture error: {e}")
            return f"Could not capture the screen: {e}."

        # Convert to high-contrast binary image to enhance text-background separation
        bin_img = cls.to_binary(raw, threshold=threshold, blur=blur)
        data, w, h, kb = cls.compress(bin_img)
        logger.info(f"ScreenReader: AI binary vision image {w}×{h} {kb:.1f} KB")

        # ── b) Try Gemini Vision ───────────────────────────────────────────────
        if settings.gemini_api_key and settings.gemini_api_key.strip():
            try:
                from google.genai import types as gtypes

                client = cls._get_gemini_client()

                image_part = gtypes.Part.from_bytes(
                    data=data,
                    mime_type="image/png",
                )
                text_part = gtypes.Part.from_text(
                    text=(
                        prompt + "\n\n"
                        "Rules:\n"
                        "- Reply in plain spoken English (no markdown, no bullet points, no code).\n"
                        "- Maximum 3 sentences.\n"
                        "- If you see code, name the language and briefly what it does.\n"
                        "- If you see a browser, mention the website.\n"
                        "- If you see a folder or files, mention what they are.\n"
                        "- If you see an error message, read it aloud verbatim.\n"
                        "- If you see any open applications or windows, mention them."
                    )
                )

                # Use the configured model name (gemini-2.5-flash supports vision)
                vision_model = settings.ai_model_name
                response = client.models.generate_content(
                    model=vision_model,
                    contents=[image_part, text_part],
                    config=gtypes.GenerateContentConfig(temperature=0.2),
                )
                description = (response.text or "").strip()
                # Strip any stray markdown
                description = description.replace("**", "").replace("*", "").replace("#", "")
                return description if description else "I could see the screen but could not generate a description."

            except Exception as exc:
                logger.warning(f"ScreenReader: Gemini vision failed: {exc}")
                # Invalidate cached client in case the key/network changed
                cls._gemini_client = None
                return (
                    "I captured the screen but could not analyse it because the AI service is unavailable. "
                    f"The binary image is {w} by {h} pixels and {kb:.1f} kilobytes."
                )

        # ── c) No AI configured ───────────────────────────────────────────────
        return (
            "Screen captured successfully. "
            f"The image is {w} by {h} pixels at {kb:.1f} kilobytes. "
            "To get a full description, configure a Gemini API key in your .env file."
        )

    # ── 6. Save for user ──────────────────────────────────────────────────────

    @classmethod
    def save_for_user(cls, binary: bool = True) -> Tuple[Path, str]:
        """
        Capture + binary threshold + compress → save timestamped file to
        Pictures/Screenshots (or Desktop as fallback).

        Returns (saved_path, spoken_confirmation).
        """
        from app.filesystem.paths import WindowsPathResolver

        standard = WindowsPathResolver.get_standard_folders()
        screenshots_dir = standard["Pictures"] / "Screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        if not screenshots_dir.is_dir():
            screenshots_dir = standard["Desktop"]

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        ext = "png"
        filepath = screenshots_dir / f"Clembot_Screenshot_{timestamp}.{ext}"

        data, info = cls.capture_and_compress(save_path=filepath, binary=binary)
        return filepath, f"Screenshot saved. {info}."


# Singleton for import convenience
screen_reader = ScreenReader()
