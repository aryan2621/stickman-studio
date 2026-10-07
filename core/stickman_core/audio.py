"""The soundtrack: a music bed, transition whooshes, and the final mix under the narration.

The music is composed here rather than shipped as files: a few chords played by a soft pad, a
plucked arpeggio and a low bass, with a little echo. It's quiet background texture, there so the
pauses between lines never fall into dead silence, and it ducks whenever the narrator speaks.
Everything is generated with numpy at 48 kHz stereo; ffmpeg only encodes the result.
"""

import subprocess

import numpy as np

from . import paths

RATE = 48000

# Moods: tempo, and four chords (MIDI note numbers, root first) played one per bar, on repeat.
MOODS = {
    "curious": {"bpm": 84, "chords": [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]},  # Am F C G
    "calm": {"bpm": 68, "chords": [[48, 52, 55, 59], [45, 48, 52, 55], [53, 57, 60, 64], [55, 59, 62, 65]]},  # Cmaj7 Am7 Fmaj7 G7
    "uplifting": {"bpm": 100, "chords": [[48, 52, 55], [55, 59, 62], [57, 60, 64], [53, 57, 60]]},  # C G Am F
}


def _hz(note: float) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def _envelope(n: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(n, dtype=np.float32)
    a, r = min(n, int(attack * RATE)), min(n, int(release * RATE))
    if a:
        env[:a] = np.linspace(0, 1, a, dtype=np.float32)
    if r:
        env[n - r:] *= np.linspace(1, 0, r, dtype=np.float32)
    return env


def _pad(freq: float, n: int, detune: float) -> np.ndarray:
    """A soft, warm tone: a few odd and even harmonics falling away quickly (a filtered saw)."""
    t = np.arange(n, dtype=np.float32) / RATE
    f = freq * (1 + detune)
    wave = sum(np.sin(2 * np.pi * f * k * t) / (k ** 1.6) for k in range(1, 6))
    return (wave * _envelope(n, 0.8, 1.0)).astype(np.float32)


def _pluck(freq: float, n: int) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / RATE
    wave = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)
    return (wave * np.exp(-t / 0.28) * _envelope(n, 0.004, 0.05)).astype(np.float32)


def _echo(stereo: np.ndarray) -> np.ndarray:
    """A small room: a few delayed, quieter copies bouncing between the channels."""
    out = stereo.copy()
    for delay, gain in ((0.19, 0.32), (0.31, 0.22), (0.47, 0.14), (0.71, 0.08)):
        d = int(delay * RATE)
        out[d:, 0] += gain * stereo[:-d, 1]
        out[d:, 1] += gain * stereo[:-d, 0]
    return out


def music(mood: str, seconds: float) -> np.ndarray:
    """A music bed `seconds` long (stereo float32), fading in and out."""
    spec = MOODS[mood]
    beat = 60 / spec["bpm"]
    bar = 4 * beat
    total = int(seconds * RATE) + 1
    out = np.zeros((total, 2), dtype=np.float32)
    bar_n = int(bar * RATE)
    eighth_n = int(beat / 2 * RATE)
    for b in range(int(seconds / bar) + 2):
        chord = spec["chords"][b % len(spec["chords"])]
        start = int(b * bar * RATE)
        if start >= total:
            break
        length = min(bar_n + int(0.9 * RATE), total - start)  # chords overlap a little as they ring out
        # Pad: each chord note, two slightly detuned voices spread left and right.
        for note in chord:
            out[start:start + length, 0] += 0.05 * _pad(_hz(note), length, -0.0018)
            out[start:start + length, 1] += 0.05 * _pad(_hz(note), length, 0.0018)
        # Bass: the root, two octaves down.
        bass = 0.12 * _pad(_hz(chord[0] - 24), min(bar_n, total - start), 0)
        out[start:start + len(bass)] += bass[:, None]
        # Arpeggio: chord notes an octave up, up and down in eighths, from the second bar on.
        if b >= 1:
            pattern = [0, 1, 2, 1, 2, 1, 0, 1] if len(chord) == 3 else [0, 1, 2, 3, 2, 3, 1, 2]
            for i, idx in enumerate(pattern):
                s = start + i * eighth_n
                n = min(int(0.6 * RATE), total - s)
                if n <= 0:
                    break
                pan = 0.35 + 0.3 * (i % 2)
                p = 0.045 * _pluck(_hz(chord[idx] + 12), n)
                out[s:s + n, 0] += p * (1 - pan)
                out[s:s + n, 1] += p * pan
    out = _echo(out)
    out *= _envelope(total, 1.5, 2.5)[:, None]
    return out / max(1e-6, np.abs(out).max()) * 0.5


def load_file(path, seconds: float) -> np.ndarray:
    """The user's own music file, decoded by ffmpeg and looped to `seconds`, fading out."""
    raw = subprocess.run(
        [paths.ffmpeg(), "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(RATE), "-"],
        capture_output=True, check=True,
    ).stdout
    track = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
    total = int(seconds * RATE) + 1
    if len(track) == 0:
        return np.zeros((total, 2), dtype=np.float32)
    track = np.tile(track, (total // len(track) + 1, 1))[:total].copy()
    track *= _envelope(total, 0.3, 2.5)[:, None]
    return track / max(1e-6, np.abs(track).max()) * 0.5


def whoosh(seconds: float = 0.42, seed: int = 0) -> np.ndarray:
    """A soft airy sweep for a transition: noise through a filter that opens and closes,
    panning across. Its loudest point is at the middle."""
    n = int(seconds * RATE)
    noise = np.random.default_rng(seed).standard_normal(n).astype(np.float32)
    shape = np.sin(np.linspace(0, np.pi, n)) ** 2
    # One-pole low-pass whose cutoff follows the shape (sample by sample; it's short).
    out = np.empty(n, dtype=np.float32)
    y = 0.0
    for i in range(n):
        a = 0.02 + 0.5 * shape[i]
        y += a * (noise[i] - y)
        out[i] = y
    out *= shape
    out /= max(1e-6, np.abs(out).max())
    pan = np.linspace(0.2, 0.8, n, dtype=np.float32)
    return np.stack([out * (1 - pan), out * pan], axis=1) * 0.22


def mix(voice: np.ndarray, voice_rate: int, bed: np.ndarray | None, effects: list[tuple[float, np.ndarray]]) -> np.ndarray:
    """Voice (mono int16 at `voice_rate`) over the music bed, which dips while the voice speaks,
    plus effects placed at their times. Returns stereo int16 at 48 kHz."""
    v = voice.astype(np.float32) / 32768
    # Resample the narration to 48 kHz (linear interpolation is clean for a 2x step).
    positions = np.arange(int(len(v) * RATE / voice_rate)) * (voice_rate / RATE)
    v = np.interp(positions, np.arange(len(v)), v).astype(np.float32)
    total = len(v)
    out = np.repeat(v[:, None], 2, axis=1)
    if bed is not None:
        bed = bed[:total] if len(bed) >= total else np.pad(bed, ((0, total - len(bed)), (0, 0)))
        # Ducking: follow the voice's loudness with a fast attack and slow release.
        level = np.abs(v)
        hop = RATE // 100
        frames = level[: len(level) // hop * hop].reshape(-1, hop).max(axis=1)
        smooth = np.zeros_like(frames)
        state = 0.0
        for i, x in enumerate(frames):
            state = max(x, state * 0.93)  # ~0.15 s release per 10 ms step
            smooth[i] = state
        speaking = np.clip(np.repeat(smooth, hop) / 0.08, 0, 1)
        speaking = np.pad(speaking, (0, total - len(speaking)), mode="edge")
        gain = 0.30 - 0.18 * speaking  # quieter under the voice, fuller in the gaps
        out += bed * gain[:, None]
    for at, clip in effects:
        i = max(0, int(at * RATE) - len(clip) // 2)
        j = min(total, i + len(clip))
        out[i:j] += clip[: j - i]
    peak = np.abs(out).max()
    if peak > 0.98:
        out *= 0.98 / peak
    return (out * 32767).astype(np.int16)


SAMPLE_SECONDS = 15
SAMPLE_VERSION = 1  # bump when the music changes, so cached samples are made again


def sample(mood: str):
    """A short sample of a mood's music, for the preview button (made once, then cached)."""
    import wave

    from . import paths

    if mood not in MOODS:
        raise ValueError("Unknown music")
    folder = paths.data_dir() / "music-samples"
    folder.mkdir(exist_ok=True)
    path = folder / f"{mood}-v{SAMPLE_VERSION}.wav"
    if not path.exists():
        pcm = (music(mood, SAMPLE_SECONDS) * 0.9 * 32767).astype(np.int16)
        partial = path.with_suffix(".part")
        with wave.open(str(partial), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm.tobytes())
        partial.replace(path)
    return str(path)
