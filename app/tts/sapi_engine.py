import sys
from typing import Any, Dict, List, Optional

try:
    import pyttsx3
    import pythoncom
    _HAS_SAPI = True
except ImportError:
    pyttsx3 = None  # type: ignore[assignment]
    pythoncom = None  # type: ignore[assignment]
    _HAS_SAPI = False

from app.config.settings import settings
from app.logging.logger import logger
from app.tts.base import BaseTTSProvider


class SAPIEngine(BaseTTSProvider):
    """
    Windows native SAPI 5 speech engine using pyttsx3.
    Provides offline, zero-latency text-to-speech without external cloud APIs.
    """

    def __init__(self):
        self._voice_id = settings.tts_voice_id
        self._rate = settings.tts_rate
        self._volume = settings.tts_volume

    def _create_engine(self):
        """Creates and configures a fresh pyttsx3 engine instance for the current thread."""
        if not _HAS_SAPI:
            raise RuntimeError(
                "SAPIEngine requires pyttsx3 and pythoncom (Windows only). "
                "On macOS, use MacOSTTSEngine instead."
            )
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass

        engine = pyttsx3.init("sapi5")
        engine.setProperty("rate", self._rate)
        engine.setProperty("volume", self._volume)

        if self._voice_id:
            try:
                engine.setProperty("voice", self._voice_id)
            except Exception as e:
                logger.debug(f"Could not set custom voice {self._voice_id}: {e}")

        return engine

    def speak(self, text: str) -> None:
        """Speaks text synchronously on the calling thread."""
        if not text or not text.strip():
            return

        try:
            engine = self._create_engine()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            logger.error(f"SAPI speech error: {e}")

    def stop(self) -> None:
        """Stops active speech."""
        try:
            engine = self._create_engine()
            engine.stop()
        except Exception as e:
            logger.debug(f"SAPI stop error: {e}")

    def get_voices(self) -> List[Dict[str, Any]]:
        """Enumerates installed Windows SAPI voices."""
        voices_list = []
        try:
            engine = self._create_engine()
            voices = engine.getProperty("voices")
            for v in voices:
                voices_list.append({
                    "id": v.id,
                    "name": v.name,
                    "languages": getattr(v, "languages", []),
                    "gender": getattr(v, "gender", None)
                })
        except Exception as e:
            logger.error(f"Failed to enumerate voices: {e}")
        return voices_list

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = voice_id

    def set_rate(self, rate: int) -> None:
        self._rate = max(50, min(400, rate))

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
