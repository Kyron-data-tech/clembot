"""
app/platform_layer/macos/tts.py

Native macOS Text-To-Speech engine using /usr/bin/say.
Implements BaseTTSProvider with zero external dependencies and native Apple Silicon support.
"""

import re
import subprocess
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.logging.logger import logger
from app.tts.base import BaseTTSProvider


class MacOSTTSEngine(BaseTTSProvider):
    """Native macOS TTS engine wrapping /usr/bin/say."""

    def __init__(self):
        self._voice_id: Optional[str] = getattr(settings, "tts_voice_id", None) or "Samantha"
        self._rate: int = getattr(settings, "tts_rate", 200)
        self._volume: float = getattr(settings, "tts_volume", 1.0)
        self._current_proc: Optional[subprocess.Popen] = None

    def speak(self, text: str) -> None:
        """Speaks the text synchronously using /usr/bin/say."""
        if not text or not text.strip():
            return

        cmd = ["/usr/bin/say"]
        if self._voice_id:
            cmd.extend(["-v", self._voice_id])
        if self._rate:
            cmd.extend(["-r", str(self._rate)])

        # Wrap text with volume modulation if supported
        clean_text = text.strip()
        cmd.append(clean_text)

        try:
            self._current_proc = subprocess.Popen(cmd)
            self._current_proc.wait()
        except FileNotFoundError:
            logger.warning("/usr/bin/say not found; TTS is unavailable on this environment.")
        except Exception as e:
            logger.error(f"macOS TTS speech error: {e}")
        finally:
            self._current_proc = None

    def stop(self) -> None:
        """Stops active speech immediately."""
        if self._current_proc:
            try:
                self._current_proc.terminate()
            except Exception:
                pass
            self._current_proc = None

        try:
            subprocess.run(["pkill", "-x", "say"], check=False)
        except Exception:
            pass

    def get_voices(self) -> List[Dict[str, Any]]:
        """Queries available macOS voices from /usr/bin/say -v '?'."""
        voices = []
        try:
            proc = subprocess.run(["/usr/bin/say", "-v", "?"], capture_output=True, text=True, timeout=3.0)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    # Format: VoiceName       locale    # Description
                    parts = re.split(r'\s{2,}', line.strip())
                    if parts:
                        vname = parts[0]
                        vlocale = parts[1] if len(parts) > 1 else ""
                        voices.append({
                            "id": vname,
                            "name": vname,
                            "languages": [vlocale],
                            "gender": "unknown"
                        })
        except Exception as e:
            logger.debug(f"Error querying macOS voices: {e}")

        if not voices:
            # Common default macOS voices
            for name in ["Samantha", "Alex", "Victoria", "Fred"]:
                voices.append({"id": name, "name": name, "languages": ["en_US"], "gender": "unknown"})

        return voices

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = voice_id

    def set_rate(self, rate: int) -> None:
        self._rate = rate

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
