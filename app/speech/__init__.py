from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.speech.base import BaseSpeechRecognizer
    from app.speech.engine import SpeechEngine
    from app.speech.wake_word import WakeWordDetector


def __getattr__(name: str):
    if name == "BaseSpeechRecognizer":
        from app.speech.base import BaseSpeechRecognizer
        return BaseSpeechRecognizer
    elif name == "SpeechEngine":
        from app.speech.engine import SpeechEngine
        return SpeechEngine
    elif name == "WakeWordDetector":
        from app.speech.wake_word import WakeWordDetector
        return WakeWordDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BaseSpeechRecognizer", "SpeechEngine", "WakeWordDetector"]
