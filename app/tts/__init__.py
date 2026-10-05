from typing import TYPE_CHECKING
from app.tts.base import BaseTTSProvider

if TYPE_CHECKING:
    from app.tts.voice_service import VoiceService, voice_service


def __getattr__(name: str):
    if name in ("VoiceService", "voice_service"):
        from app.tts.voice_service import VoiceService, voice_service
        return VoiceService if name == "VoiceService" else voice_service
    elif name == "SAPIEngine":
        from app.tts.sapi_engine import SAPIEngine
        return SAPIEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BaseTTSProvider", "VoiceService", "voice_service"]
