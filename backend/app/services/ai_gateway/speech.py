"""SpeechToTextService: faster-whisper behind the AI boundary.

The Interview Agent never sees audio — the API transcribes, then submits the
transcript through the normal text answer path. faster-whisper decodes
audio through PyAV (bundled FFmpeg libraries), so browser MediaRecorder
output (webm/opus, ogg, mp4/aac, wav) works without a system ffmpeg.

Defaults to CPU + int8 (the recommended quantized CPU mode); set
WHISPER_DEVICE=cuda and WHISPER_COMPUTE_TYPE=float16 on an NVIDIA host.
"""

import threading

from app.core.config import get_settings
from app.services.ai_gateway.embeddings import _IdleReleasedModel

settings = get_settings()


class SpeechToTextService(_IdleReleasedModel):
    """Released after MODEL_IDLE_UNLOAD_SECONDS like the embedding models."""

    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        super().__init__(model_name)
        self.device = device
        self.compute_type = compute_type

    def _build(self):
        from faster_whisper import WhisperModel

        return WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)

    def transcribe(self, audio_path: str) -> dict:
        def decode(model):
            # segments is a lazy generator: consume it while the model is held.
            segments, info = model.transcribe(audio_path, beam_size=5, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip(), info

        text, info = self._run(decode)
        return {
            "text": text,
            "language": info.language,
            "language_probability": round(float(info.language_probability), 4),
            "duration_seconds": round(float(info.duration), 2),
            "model": self.model_name,
        }


_service: SpeechToTextService | None = None
_lock = threading.Lock()


def get_speech_service() -> SpeechToTextService:
    global _service
    with _lock:
        if _service is None:
            _service = SpeechToTextService(settings.WHISPER_MODEL, settings.WHISPER_DEVICE, settings.WHISPER_COMPUTE_TYPE)
    return _service
