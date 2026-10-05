import queue
import re
import threading
from typing import Optional

from app.config.settings import settings
from app.core.event_bus import event_bus
from app.logging.logger import logger
from app.platform_layer import platform_adapter
from app.tts.base import BaseTTSProvider


class VoiceService:
    """
    Asynchronous, non-blocking Voice Service for Clembot.
    Runs a dedicated background worker to process spoken phrases sequentially.
    """

    def __init__(self, provider: Optional[BaseTTSProvider] = None):
        self.provider = provider or platform_adapter.create_tts_engine()
        self.queue: queue.Queue = queue.Queue()
        self.enabled = settings.tts_enabled
        self._stop_event = threading.Event()
        self._current_speech_thread: Optional[threading.Thread] = None
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="Clembot-TTS-Worker")
        self._worker_thread.start()

    def speak(self, text: str, interrupt: bool = False) -> None:
        """Queues a phrase to be spoken aloud."""
        if not self.enabled or not text or not text.strip():
            return

        cleaned = re.sub(r'```[^`]*```', '', text, flags=re.DOTALL)
        cleaned = re.sub(r'[*_`#]+', '', cleaned).strip()
        if not cleaned:
            return

        if interrupt:
            self.stop()

        self.queue.put(cleaned)

    def stop(self) -> None:
        """Clears the speech queue and stops active speech."""
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except (queue.Empty, ValueError):
                break
        self.provider.stop()

    def mute(self) -> None:
        """Mutes speech output."""
        self.enabled = False
        self.stop()
        event_bus.emit("tts_muted")

    def unmute(self) -> None:
        """Unmutes speech output."""
        self.enabled = True
        event_bus.emit("tts_unmuted")

    def _worker_loop(self) -> None:
        """Worker thread loop consuming the speech queue."""
        while not self._stop_event.is_set():
            try:
                text = self.queue.get(timeout=0.5)
                if text is None:
                    break

                if self.enabled:
                    event_bus.emit("tts_start", text)
                    logger.info(f"Clembot Speaking: \"{text}\"")
                    self.provider.speak(text)
                    event_bus.emit("tts_end", text)

                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in TTS worker: {e}")


# Global VoiceService singleton
voice_service = VoiceService()
