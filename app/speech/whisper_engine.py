"""
app/speech/whisper_engine.py

Offline Speech-to-Text engine using faster-whisper (CTranslate2-optimised Whisper).

Key advantages over Google STT:
  - 100% offline after first model download (~40 MB for tiny.en)
  - Far more accurate on compound spoken phrases like "in line 36 replace I with J"
  - No internet required, no API key, no rate limits
  - Configurable model size / device via settings

Usage: set CLEMBOT_STT_PROVIDER=whisper in .env
       optionally set WHISPER_MODEL_SIZE=base.en for higher accuracy
"""

import queue
import threading
import time
from typing import Callable, List, Optional

import numpy as np

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False

from app.config.settings import settings
from app.core.event_bus import event_bus
from app.logging.logger import logger
from app.speech.base import BaseSpeechRecognizer


class WhisperEngine(BaseSpeechRecognizer):
    """
    Offline speech recognition engine using faster-whisper.

    Architecture mirrors SpeechEngine:
      sounddevice audio capture → energy VAD → chunk accumulation
      → faster_whisper.WhisperModel.transcribe() → speech_recognized event

    Model is loaded lazily on first start() call to avoid slowing imports.
    """

    SAMPLE_RATE = 16000
    CHANNELS = 1
    BLOCK_SIZE = 1600  # 100ms chunks
    INITIAL_PROMPT = "Clembot, activate, deactivate, VS Code, Python, terminal, line, tab, Chrome, Brave, open folder, replace, insert, delete, show line."

    def __init__(self):
        self.mic_index: Optional[int] = settings.mic_device_index
        self._is_running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

        self._current_callback: Optional[Callable[[str], None]] = None
        self._current_error_callback: Optional[Callable[[str], None]] = None

        # Lazy-loaded model
        self._model = None
        self._model_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self):
        """Load or return the cached WhisperModel. Thread-safe."""
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
                logger.info(
                    f"Loading Whisper model '{settings.whisper_model_size}' "
                    f"on {settings.whisper_device} ({settings.whisper_compute_type})…"
                )
                self._model = WhisperModel(
                    settings.whisper_model_size,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute_type,
                )
                logger.info("Whisper model loaded successfully.")
            except ImportError:
                logger.error(
                    "faster-whisper is not installed. "
                    "Run: pip install faster-whisper  — then restart Clembot."
                )
                raise
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise
        return self._model

    # ------------------------------------------------------------------
    # Public interface (BaseSpeechRecognizer)
    # ------------------------------------------------------------------

    @classmethod
    def get_microphones(cls) -> List[str]:
        """Returns available input microphone names from sounddevice."""
        mic_names = []
        if not _SD_AVAILABLE:
            return ["Default System Microphone"]
        try:
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    mic_names.append(f"{idx}: {dev.get('name', 'Microphone')}")
        except Exception as e:
            logger.error(f"Failed to list microphones: {e}")
        return mic_names or ["Default System Microphone"]

    def set_microphone(self, index: Optional[int]) -> None:
        """Sets the active input microphone index."""
        with self._lock:
            self.mic_index = index
            was_running = self._is_running
            if was_running:
                self.stop()
                if self._current_callback:
                    self.start(self._current_callback, self._current_error_callback)

    def start(
        self,
        on_speech_recognized: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Start continuous background listening using sounddevice + Whisper."""
        if not _SD_AVAILABLE:
            logger.error("sounddevice is not installed — cannot start WhisperEngine.")
            return

        # Pre-load model so first utterance isn't slow
        try:
            self._load_model()
        except Exception:
            return  # error already logged

        with self._lock:
            if self._is_running:
                return
            self._current_callback = on_speech_recognized
            self._current_error_callback = on_error
            self._is_running = True
            self._stop_event.clear()

            self._worker_thread = threading.Thread(
                target=self._continuous_listen_loop,
                daemon=True,
                name="Clembot-WhisperListener",
            )
            self._worker_thread.start()
            logger.info("WhisperEngine started (offline STT active).")
            event_bus.emit("speech_engine_started")

    def stop(self) -> None:
        """Stop background listening."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

        logger.info("WhisperEngine stopped.")
        event_bus.emit("speech_engine_stopped")

    # ------------------------------------------------------------------
    # Internal audio capture loop
    # ------------------------------------------------------------------

    def _continuous_listen_loop(self) -> None:
        """Worker loop: sounddevice capture → energy VAD → Whisper transcription."""

        def _callback(indata, frames, time_info, status):
            if self._is_running:
                self._audio_queue.put(indata.copy())

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype="int16",
                blocksize=self.BLOCK_SIZE,
                device=self.mic_index,
                callback=_callback,
            ):
                logger.info("WhisperEngine audio stream opened.")

                ambient_energy = self._calibrate_ambient()
                logger.info(f"WhisperEngine ambient calibration: {ambient_energy:.1f}")

                speech_buffer: List[np.ndarray] = []
                is_speaking = False
                silence_frames = 0
                max_silence_frames = int(settings.speech_pause_threshold * 10)
                max_phrase_frames = int(settings.speech_phrase_time_limit * 10)

                while not self._stop_event.is_set():
                    try:
                        chunk = self._audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    float_chunk = chunk.astype(np.float64)
                    rms = np.sqrt(np.mean(float_chunk ** 2))
                    energy_cutoff = max(ambient_energy * 1.6, float(settings.speech_energy_threshold))

                    if rms > energy_cutoff:
                        if not is_speaking:
                            is_speaking = True
                            event_bus.emit("speech_detected")
                        speech_buffer.append(chunk)
                        silence_frames = 0
                    elif is_speaking:
                        speech_buffer.append(chunk)
                        silence_frames += 1
                        if silence_frames >= max_silence_frames or len(speech_buffer) >= max_phrase_frames:
                            self._transcribe_and_emit(speech_buffer)
                            speech_buffer = []
                            is_speaking = False
                            silence_frames = 0

        except Exception as e:
            self._is_running = False
            err_msg = f"WhisperEngine audio capture error: {e}"
            logger.error(err_msg)
            event_bus.emit("speech_error", err_msg)
            if self._current_error_callback:
                self._current_error_callback(err_msg)

    def _calibrate_ambient(self, duration_sec: float = 0.5) -> float:
        """Compute baseline RMS over duration_sec."""
        energies = []
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            try:
                chunk = self._audio_queue.get(timeout=0.1)
                rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
                energies.append(rms)
            except queue.Empty:
                pass
        return float(np.mean(energies)) if energies else float(settings.speech_energy_threshold)

    def _transcribe_and_emit(self, chunks: List[np.ndarray]) -> None:
        """Transcribe accumulated PCM chunks via Whisper and emit speech_recognized."""
        if not chunks or len(chunks) < 3:
            return
        try:
            # Concatenate and convert to float32 in [-1, 1] range (Whisper expects this)
            pcm = np.concatenate(chunks).astype(np.float32) / 32768.0
            event_bus.emit("speech_processing")

            model = self._model
            if model is None:
                return

            lang = "en" if settings.whisper_model_size.endswith(".en") else None
            segments, _info = model.transcribe(
                pcm,
                language=lang,
                beam_size=1,           # fast greedy decode
                vad_filter=True,       # built-in silence suppression
                vad_parameters={"min_silence_duration_ms": 300},
                initial_prompt=self.INITIAL_PROMPT,
            )

            # Collect all segment texts
            text = " ".join(seg.text for seg in segments).strip()
            # Strip Whisper hallucination artifacts (e.g. "[BLANK_AUDIO]", "(music)")
            text = _clean_whisper_output(text)

            if text:
                logger.info(f"Whisper recognised: \"{text}\"")
                event_bus.emit("speech_recognized", text)

        except Exception as e:
            logger.error(f"WhisperEngine transcription error: {e}")

    # ------------------------------------------------------------------
    # Push-to-Talk
    # ------------------------------------------------------------------

    def listen_once(self, timeout: float = 5.0) -> Optional[str]:
        """Capture a single Push-to-Talk utterance and return the transcript."""
        if not _SD_AVAILABLE:
            return None

        event_bus.emit("push_to_talk_recording_started")
        logger.info("Whisper push-to-talk recording started…")

        recorded_chunks: List[np.ndarray] = []
        stop_recording = False

        def _ptt_callback(indata, frames, time_info, status):
            if not stop_recording:
                recorded_chunks.append(indata.copy())

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype="int16",
                blocksize=self.BLOCK_SIZE,
                device=self.mic_index,
                callback=_ptt_callback,
            ):
                start_time = time.time()
                has_started_speaking = False
                silence_frames = 0

                while time.time() - start_time < timeout:
                    time.sleep(0.1)
                    if recorded_chunks:
                        recent = recorded_chunks[-1].astype(np.float64)
                        rms = np.sqrt(np.mean(recent ** 2))
                        if rms > settings.speech_energy_threshold:
                            has_started_speaking = True
                            silence_frames = 0
                        elif has_started_speaking:
                            silence_frames += 1
                            if silence_frames > 8:
                                break

                stop_recording = True

            event_bus.emit("push_to_talk_processing")

            if recorded_chunks:
                pcm = np.concatenate(recorded_chunks).astype(np.float32) / 32768.0
                model = self._load_model()
                lang = "en" if settings.whisper_model_size.endswith(".en") else None
                segments, _ = model.transcribe(
                    pcm,
                    language=lang,
                    beam_size=1,
                    vad_filter=True,
                    initial_prompt=self.INITIAL_PROMPT,
                )
                text = " ".join(seg.text for seg in segments).strip()
                text = _clean_whisper_output(text)
                if text:
                    logger.info(f"Whisper PTT recognised: \"{text}\"")
                    event_bus.emit("speech_recognized", text)
                    return text

        except Exception as e:
            logger.error(f"Whisper push-to-talk error: {e}")
        finally:
            event_bus.emit("push_to_talk_recording_ended")

        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_whisper_output(text: str) -> str:
    """
    Remove Whisper hallucination artifacts and normalise the transcript.
    Whisper sometimes produces bracketed noise/music labels on silent audio.
    """
    import re
    # Strip [BLANK_AUDIO], (music), [noise], etc.
    text = re.sub(r'\[.*?\]|\(.*?\)', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Drop very short outputs that are likely artifacts
    if len(text) < 2:
        return ""
    return text
