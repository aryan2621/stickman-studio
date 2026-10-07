"""The narrator: Kokoro (82M parameters, ONNX on the CPU) reads each shot's line.

The narrator's voice reads the narration, identical across the whole video (the skill's narrator
lock, for free); in a story with character voices each character's lines are read in their own
voice. Each shot's audio length sets how long the shot stays on screen.
"""

import threading
import wave

import numpy as np

from . import models, styles

SAMPLE_RATE = 24000

_kokoro = None
_lock = threading.Lock()


def _engine():
    global _kokoro
    with _lock:
        if _kokoro is None:
            from kokoro_onnx import Kokoro

            _kokoro = Kokoro(str(models.path("kokoro")), str(models.path("kokoro-voices")))
        return _kokoro


def speak(text: str, voice: str, speed: float, out_path) -> float:
    """Writes the narration to a 24 kHz mono WAV and returns its length in seconds."""
    if voice not in styles.VOICES:
        raise ValueError(f"Unknown voice: {voice}")
    samples, rate = _engine().create(text, voice=voice, speed=speed, lang=styles.speech_lang(voice))
    samples = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return len(pcm) / rate


def read_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1:
            raise ValueError(f"Unexpected audio format in {path}")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
