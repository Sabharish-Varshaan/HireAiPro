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

settings = get_settings()


class SpeechToTextService:
    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: str) -> dict:
        segments, info = self._load().transcribe(audio_path, beam_size=5, vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
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
