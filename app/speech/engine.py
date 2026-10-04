import math
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional
import numpy as np
import sounddevice as sd
import speech_recognition as sr

from app.config.settings import settings
from app.core.event_bus import event_bus
from app.logging.logger import logger
from app.speech.base import BaseSpeechRecognizer


class SpeechEngine(BaseSpeechRecognizer):
    """
    Robust Windows Speech Engine using sounddevice for native audio capture
    and SpeechRecognition for speech-to-text.
    Supports continuous background listening, real-time energy VAD, and Push-to-Talk.
    Works natively on Windows 10/11 without requiring PyAudio.
    """

    SAMPLE_RATE = 16000
    CHANNELS = 1
    BLOCK_SIZE = 1600  # 100ms chunks at 16kHz

    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = settings.speech_energy_threshold
        self.recognizer.dynamic_energy_threshold = settings.speech_dynamic_energy_threshold
        self.recognizer.pause_threshold = settings.speech_pause_threshold

        self.mic_index = settings.mic_device_index
        self._is_running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

        # Bounded pool for STT network calls — keeps audio loop non-blocking.
        # Max 2 concurrent recognitions (avoids rate-limit pile-up on slow networks).
        self._stt_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Clembot-STT")

        self._current_callback: Optional[Callable[[str], None]] = None
        self._current_error_callback: Optional[Callable[[str], None]] = None

    @classmethod
    def get_microphones(cls) -> List[str]:
        """Returns a list of input microphone device names from sounddevice."""
        mic_names = []
        try:
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    mic_names.append(f"{idx}: {dev.get('name', 'Microphone')}")
        except Exception as e:
            logger.error(f"Failed to list sounddevice microphones: {e}")

        if not mic_names:
            mic_names = ["Default System Microphone"]
        return mic_names

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
        on_error: Optional[Callable[[str], None]] = None
    ) -> None:
        """Starts continuous non-blocking background listening using sounddevice."""
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
                name="Clembot-SoundDeviceListener"
            )
            self._worker_thread.start()
            logger.info("Speech recognition engine started with native sounddevice audio capture.")
            event_bus.emit("speech_engine_started")

    def stop(self) -> None:
        """Stops background listening."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False
            self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.5)

        # Drain in-flight STT requests with a short timeout
        self._stt_pool.shutdown(wait=True, cancel_futures=False)
        # Recreate pool for potential restart
        self._stt_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Clembot-STT")

        logger.info("Speech recognition engine stopped.")
        event_bus.emit("speech_engine_stopped")

    def _continuous_listen_loop(self) -> None:
        """Worker loop reading continuous audio stream and performing energy-based VAD."""
        # Audio callback pushing 100ms raw PCM chunks
        def _callback(indata, frames, time_info, status):
            if self._is_running:
                # Copy numpy array buffer
                self._audio_queue.put(indata.copy())

        try:
            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype="int16",
                blocksize=self.BLOCK_SIZE,
                device=self.mic_index,
                callback=_callback
            ):
                logger.info("Audio stream successfully opened on microphone.")

                # 1. Calibrate initial ambient noise
                ambient_energy = self._calibrate_ambient()
                logger.info(f"Calibrated ambient energy threshold: {ambient_energy:.1f}")

                speech_buffer: List[np.ndarray] = []
                is_speaking = False
                silence_frames = 0
                max_silence_frames = int(settings.speech_pause_threshold * 10)  # ~8 frames (800ms)
                max_phrase_frames = int(settings.speech_phrase_time_limit * 10) # 120 frames (12s)

                while not self._stop_event.is_set():
                    try:
                        chunk = self._audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    # Calculate RMS energy of current 100ms chunk
                    float_chunk = chunk.astype(np.float64)
                    rms = np.sqrt(np.mean(float_chunk**2))

                    energy_cutoff = max(ambient_energy * 1.6, float(settings.speech_energy_threshold))

                    if rms > energy_cutoff:
                        if not is_speaking:
                            is_speaking = True
                            event_bus.emit("speech_detected")
                        speech_buffer.append(chunk)
                        silence_frames = 0
                    elif is_speaking:
                        # User was speaking, now a quiet chunk
                        speech_buffer.append(chunk)
                        silence_frames += 1

                        # Did user finish speaking?
                        if silence_frames >= max_silence_frames or len(speech_buffer) >= max_phrase_frames:
                            # Dispatch to thread pool — STT is a network call (1-5s)
                            # and must NOT block the audio buffer loop
                            utterance_copy = list(speech_buffer)
                            self._stt_pool.submit(self._process_recorded_utterance, utterance_copy)
                            speech_buffer = []
                            is_speaking = False
                            silence_frames = 0

        except Exception as e:
            self._is_running = False
            err_msg = f"Audio capture error: {e}"
            logger.error(err_msg)
            event_bus.emit("speech_error", err_msg)
            if self._current_error_callback:
                self._current_error_callback(err_msg)

    def _calibrate_ambient(self, duration_sec: float = 0.6) -> float:
        """Computes baseline ambient RMS over duration_sec."""
        time.sleep(0.1)  # Allow hardware audio callback to start delivering frames
        energies = []
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            try:
                chunk = self._audio_queue.get(timeout=0.15)
                rms = np.sqrt(np.mean(chunk.astype(np.float64)**2))
                energies.append(rms)
            except queue.Empty:
                pass
        if energies:
            return float(np.mean(energies))
        return float(settings.speech_energy_threshold)

    def _process_recorded_utterance(self, chunks: List[np.ndarray]) -> None:
        """Converts accumulated PCM chunks to SpeechRecognition AudioData and runs STT."""
        if not chunks or len(chunks) < 2:   # 200ms minimum (was 300ms — too long for short commands)
            return

        try:
            pcm_bytes = np.concatenate(chunks).tobytes()
            audio_data = sr.AudioData(pcm_bytes, self.SAMPLE_RATE, 2)

            event_bus.emit("speech_processing")
            text = self.recognizer.recognize_google(audio_data)

            if text and text.strip():
                logger.info(f"Recognized Speech: \"{text}\"")
                event_bus.emit("speech_recognized", text)

        except sr.UnknownValueError:
            # Silence or unintelligible noise
            pass
        except sr.RequestError as e:
            err_msg = f"Speech STT service error: {e}"
            logger.warning(err_msg)
            event_bus.emit("speech_error", err_msg)
            if self._current_error_callback:
                self._current_error_callback(err_msg)
        except Exception as e:
            logger.error(f"Unexpected STT error: {e}")

    def listen_once(self, timeout: float = 5.0) -> Optional[str]:
        """Captures a single utterance (Push-to-Talk) using sounddevice."""
        event_bus.emit("push_to_talk_recording_started")
        logger.info("Push-to-talk recording started...")

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
                callback=_ptt_callback
            ):
                start_time = time.time()
                has_started_speaking = False
                silence_frames = 0

                while time.time() - start_time < timeout:
                    time.sleep(0.1)
                    if recorded_chunks:
                        recent_chunk = recorded_chunks[-1].astype(np.float64)
                        rms = np.sqrt(np.mean(recent_chunk**2))
                        if rms > settings.speech_energy_threshold:
                            has_started_speaking = True
                            silence_frames = 0
                        elif has_started_speaking:
                            silence_frames += 1
                            if silence_frames > 8:  # 800ms silence
                                break

                stop_recording = True

            event_bus.emit("push_to_talk_processing")

            if recorded_chunks:
                pcm_bytes = np.concatenate(recorded_chunks).tobytes()
                audio_data = sr.AudioData(pcm_bytes, self.SAMPLE_RATE, 2)
                text = self.recognizer.recognize_google(audio_data)
                if text and text.strip():
                    logger.info(f"Push-to-talk recognized: \"{text}\"")
                    event_bus.emit("speech_recognized", text)
                    return text

        except sr.UnknownValueError:
            logger.debug("Push-to-talk detected no speech.")
        except Exception as e:
            logger.error(f"Push-to-talk error: {e}")
        finally:
            event_bus.emit("push_to_talk_recording_ended")

        return None
