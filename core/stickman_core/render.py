"""The editor: turns the drawn shots and the narration into the final MP4.

Shots cut on the voice: the picture changes just as the next line starts, with a small zoom
"punch" so the cut feels deliberate. Where the story moves to its next stage (hook → twist →
secret → truth → payoff) the new shot slides in instead, with a whoosh. Within a shot the camera
drifts along its path; when the next line shares the picture (a conversation) there's no cut at all:
the camera glides to whoever speaks next. Frames are drawn with Pillow from a fractional crop box of
the original drawing, resampled once per frame (sub-pixel smooth, unlike ffmpeg's zoompan, and
never enlarged twice), and piped to ffmpeg as raw RGB. Captions are drawn with Pillow; Hindi ones
are drawn by ffmpeg, whose HarfBuzz places Devanagari's vowel signs and conjuncts correctly.
"""

import math
import re
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import audio, paths, styles, voice

FPS = 30
LEAD = 0.25  # before the first line
TAIL = 2.0  # after the last line: the picture holds, then fades out with the music
FADE_OUT = 0.6
PAUSE_SENTENCE = 0.32  # between lines when a sentence ends
PAUSE_CONTINUE = 0.1  # between lines when the sentence carries on into the next shot
CUT_EARLY = 0.06  # the picture changes just before the voice
PUNCH = 0.25  # seconds the zoom punch takes to settle after a cut
SLIDE = 0.34  # seconds a stage change takes to slide in
GLIDE = 0.55  # seconds the camera takes to move to the next speaker in a shared picture

FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]
# Fonts that ffmpeg's HarfBuzz shapes Devanagari correctly with (Kohinoor and ITF Devanagari
# misplace the "i" vowel sign there).
DEVANAGARI_FONTS = [
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
]
HIGHLIGHT = (255, 214, 64, 255)

# Camera paths: (zoom, centre x, centre y) at the start and end, centres as fractions of the frame.
CAMERA = {
    "push_in": ((1.0, 0.5, 0.5), (1.24, 0.5, 0.45)),
    "pull_out": ((1.24, 0.5, 0.45), (1.0, 0.5, 0.5)),
    "pan_left": ((1.2, 0.59, 0.5), (1.2, 0.41, 0.5)),
    "pan_right": ((1.2, 0.41, 0.5), (1.2, 0.59, 0.5)),
    "rise": ((1.2, 0.5, 0.59), (1.2, 0.5, 0.41)),
    "still": ((1.04, 0.5, 0.5), (1.1, 0.5, 0.48)),
    "focus_left": ((1.5, 0.3, 0.45), (1.58, 0.3, 0.44)),
    "focus_center": ((1.5, 0.5, 0.45), (1.58, 0.5, 0.44)),
    "focus_right": ((1.5, 0.7, 0.45), (1.58, 0.7, 0.44)),
}


class Cancelled(Exception):
    pass


@dataclass
class Shot:
    image: Path
    audio: Path
    seconds: float
    camera: str
    caption: str
    narration: str
    stage: str
    shared: bool = False  # shows the previous shot's picture: the camera glides instead of cutting
    language: str = "en"


def _font(size: int):
    for candidate in FONTS:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size)


def _ease_out(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def _ease_in_out(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 0.5 - 0.5 * math.cos(math.pi * p)


def _drift(p: float) -> float:
    # Mostly linear (a steady drift) with softened ends.
    p = min(1.0, max(0.0, p))
    return 0.75 * p + 0.25 * (0.5 - 0.5 * math.cos(math.pi * p))


def _base(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """The drawing cropped to the frame's shape at its own resolution, lightly sharpened. Frames
    are cut from it and resampled once, so a zoomed shot is never enlarged twice."""
    aspect = size[0] / size[1]
    w, h = image.size
    if w / h > aspect:
        cw = round(h * aspect)
        image = image.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
    elif w / h < aspect:
        ch = round(w / aspect)
        image = image.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))
    # Enlarging softens edges; a gentle unsharp mask at the source size keeps lines crisp.
    return image.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))


def _view(camera: str, p: float) -> tuple[float, float, float]:
    """Where the camera is (zoom, centre x, centre y) at `p` (0..1) through the shot."""
    (z0, x0, y0), (z1, x1, y1) = CAMERA.get(camera, CAMERA["push_in"])
    e = _drift(p)
    return z0 + (z1 - z0) * e, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e


def _frame(base: Image.Image, view: tuple[float, float, float], size: tuple[int, int], punch: float = 1.0) -> Image.Image:
    z, cx, cy = view
    z *= punch
    # Keep the view inside the drawing.
    half = 0.5 / z
    cx, cy = min(max(cx, half), 1 - half), min(max(cy, half), 1 - half)
    w, h = base.size
    left, top = cx * w - w * half, cy * h - h * half
    return base.resize(size, Image.LANCZOS, box=(left, top, left + w / z, top + h / z))


# Captions


@dataclass
class Caption:
    start: float
    end: float
    layer: Image.Image  # just the caption, positioned at `at`
    at: tuple[int, int]
    pop: bool = False


class _Type:
    """Captions' lettering with Pillow (Latin text)."""

    def __init__(self, size: int):
        self.font = _font(size)
        self.size = size

    def length(self, text: str) -> float:
        return self.font.getlength(text)

    def line_height(self) -> int:
        ascent, descent = self.font.getmetrics()
        return ascent + descent

    def draw(self, layer: Image.Image, xy: tuple[float, float], text: str, fill, stroke: int = 0):
        ImageDraw.Draw(layer).text(xy, text, font=self.font, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 255))


@lru_cache(maxsize=4096)
def _shaped(text: str, size: int, stroke: int) -> Image.Image:
    """`text` in white (outlined in black when `stroke`), shaped by ffmpeg's HarfBuzz, on a
    transparent strip of fixed height with the baseline at the same place, so words line up;
    cropped to the text's width."""
    font = next((f for f in DEVANAGARI_FONTS if Path(f).exists()), None)
    if font is None:
        raise RuntimeError("No Devanagari font found on this Mac for the Hindi captions")
    height = int(size * 1.7) + stroke * 2
    width = int(len(text) * size * 0.9) + stroke * 2 + 40
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "t.txt").write_text(text, encoding="utf-8")
        out = Path(tmp) / "t.png"
        # Without a real bold face, a thin white outline gives the letters some weight.
        border = f"borderw={stroke}:bordercolor=black" if stroke else f"borderw={max(1, size // 30)}:bordercolor=white"
        draw = (f"drawtext=fontfile='{font}':textfile='{Path(tmp) / 't.txt'}':fontsize={size}:fontcolor=white:"
                f"{border}:x={stroke + 8}:y={stroke + int(size * 1.15)}:y_align=baseline")
        subprocess.run([paths.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black@0.0:s={width}x{height},format=rgba",
                        "-vf", draw, "-frames:v", "1", str(out)], check=True, capture_output=True)
        image = Image.open(out).convert("RGBA")
    box = image.getchannel("A").getbbox()
    if not box:
        return Image.new("RGBA", (max(1, size // 3), height), (0, 0, 0, 0))
    return image.crop((box[0], 0, box[2], height))


class _ShapedType:
    """Captions' lettering for scripts Pillow can't lay out here (Devanagari), drawn by ffmpeg."""

    def __init__(self, size: int):
        self.size = size

    def length(self, text: str) -> float:
        return sum(_shaped(w, self.size, 0).width for w in text.split()) + self.size * 0.3 * max(0, len(text.split()) - 1)

    def line_height(self) -> int:
        return int(self.size * 1.7)

    def draw(self, layer: Image.Image, xy: tuple[float, float], text: str, fill, stroke: int = 0):
        x, y = xy
        for word in text.split():
            glyphs = _shaped(word, self.size, stroke)
            # White becomes the fill colour; the black outline stays black.
            tinted = Image.merge("RGBA", [c.point(lambda v, k=k: v * k // 255) for c, k in zip(glyphs.split()[:3], fill[:3])] + [glyphs.getchannel("A")])
            layer.alpha_composite(tinted, dest=(int(x) - stroke, int(y) - stroke))
            x += glyphs.width - stroke * 2 + self.size * 0.3


def _complex(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", text))


def _type(size: int, text: str):
    return _ShapedType(size) if _complex(text) else _Type(size)


def _pill(words: list[str], highlight: int, face, pad: tuple[int, int]) -> Image.Image:
    """Words on a dark rounded pill, one of them highlighted (the one being spoken)."""
    space = face.length(" ") if isinstance(face, _Type) else face.size * 0.3
    widths = [face.length(w) for w in words]
    w = int(sum(widths) + space * (len(words) - 1) + pad[0] * 2)
    h = int(face.line_height() + pad[1] * 2)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 3, fill=(12, 12, 14, 190))
    x = pad[0]
    for i, (word, width) in enumerate(zip(words, widths)):
        face.draw(layer, (x, pad[1]), word, HIGHLIGHT if i == highlight else (255, 255, 255, 255))
        x += width + space
    return layer


def _words(narration: str) -> list[str]:
    """The line's words; a dash joining two words ("forward—but") counts as a break."""
    return re.sub(r"\s*([—–])\s*", r"\1 ", narration).split()


def _subtitle_chunks(words: list[str], face, max_width: float) -> list[list[str]]:
    """Two or three words at a time, breaking after punctuation, never wider than `max_width`."""
    space = face.length(" ") if isinstance(face, _Type) else face.size * 0.3
    chunks, current, width = [], [], 0.0
    for word in words:
        w = face.length(word)
        if current and width + space + w > max_width:
            chunks.append(current)
            current, width = [], 0.0
        current.append(word)
        width += (space if len(current) > 1 else 0) + w
        if len(current) >= 3 or (re.search(r"[.,!?;:—–।]$", word) and len(current) >= 2):
            chunks.append(current)
            current, width = [], 0.0
    if current:
        last = chunks[-1] if chunks else None
        if last and len(current) == 1 and len(last) < 4 and face.length(" ".join(last + current)) <= max_width:
            last.append(current[0])  # don't leave one word on its own
        else:
            chunks.append(current)
    return chunks


def _subtitles(shot: Shot, start: float, size: tuple[int, int], portrait: bool) -> list[Caption]:
    """Each chunk on its pill, with the word being spoken highlighted. Word timing is estimated
    from each word's share of the line's letters (Kokoro doesn't report word times)."""
    face = _type(70 if portrait else 56, shot.narration)
    words = _words(shot.narration)
    weights = [len(w) + 2 for w in words]
    total = sum(weights)
    times, t = [], start
    for weight in weights:
        times.append((t, t + shot.seconds * weight / total))
        t += shot.seconds * weight / total
    captions, index = [], 0
    for chunk in _subtitle_chunks(words, face, size[0] * 0.86 - 56):
        for j in range(len(chunk)):
            layer = _pill(chunk, j, face, (28, 14))
            x = (size[0] - layer.width) // 2
            y = int(size[1] * (0.8 if portrait else 0.85)) - layer.height // 2
            captions.append(Caption(times[index + j][0], times[index + j][1], layer, (x, y)))
        index += len(chunk)
    # Hold each chunk through the small gaps between words and lines.
    for a, b in zip(captions, captions[1:]):
        a.end = b.start
    return captions


def _keyword(text: str, start: float, end: float, size: tuple[int, int], portrait: bool) -> Caption:
    """Big punchy words near the top, outlined so they read on any drawing."""
    face = _type(120 if portrait else 96, text)
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if face.length(trial) <= size[0] * 0.86 or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    stroke = 10
    line_h = int(face.size * 1.15) if isinstance(face, _Type) else face.line_height()
    w = int(max(face.length(l) for l in lines)) + stroke * 2 + 8
    h = line_h * len(lines) + stroke * 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for i, l in enumerate(lines):
        x = (w - face.length(l)) / 2
        face.draw(layer, (x, stroke + i * line_h), l, HIGHLIGHT, stroke)
    return Caption(start, end, layer, ((size[0] - w) // 2, int(size[1] * (0.12 if portrait else 0.1))), pop=True)


def _draw_caption(frame: Image.Image, c: Caption, t: float):
    layer, (x, y) = c.layer, c.at
    if c.pop:
        p = _ease_out((t - c.start) / 0.18)
        if p < 1:
            scale = 0.8 + 0.2 * p
            layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BILINEAR)
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * p)))
            x += (c.layer.width - layer.width) // 2
            y += (c.layer.height - layer.height) // 2
    frame.alpha_composite(layer, dest=(x, y))


# Sketch cards for the preview


CARD_COLOURS = {  # background, text
    "classic-light": ((255, 255, 255), (40, 40, 40)),
    "classic-dark": ((10, 10, 10), (230, 230, 230)),
    "studio-tech": ((244, 246, 249), (40, 48, 60)),
    "cinematic": ((34, 26, 44), (240, 226, 210)),
}


def sketch_card(path: Path, style: str, ratio: str, index: int, stage: str, scene: str):
    """A stand-in for a shot that isn't drawn yet: its number, stage and scene, in the style's
    colours, so the preview shows the timing without waiting for the drawings."""
    w, h = styles.FORMATS[ratio]["draw"]
    bg, fg = CARD_COLOURS.get(style, CARD_COLOURS["classic-light"])
    card = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(card)
    m = int(min(w, h) * 0.08)
    d.rounded_rectangle((m, m, w - m, h - m), radius=m // 2, outline=fg, width=3)
    # A little stick figure, so it reads as a placeholder for a drawing.
    # Keep everything above the subtitle band (bottom ~30% of a vertical frame).
    cx, cy, r = w // 2, int(h * 0.15), int(min(w, h) * 0.045)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=fg, width=6)
    d.line((cx, cy + r, cx, cy + r * 4), fill=fg, width=6)
    d.line((cx - r * 2, cy + r * 2, cx + r * 2, cy + r * 2), fill=fg, width=6)
    d.line((cx, cy + r * 4, cx - r * 1.5, cy + r * 6), fill=fg, width=6)
    d.line((cx, cy + r * 4, cx + r * 1.5, cy + r * 6), fill=fg, width=6)
    label = _font(int(min(w, h) * 0.045))
    d.text((w / 2, cy + r * 7.5), f"SHOT {index + 1}  |  {stage.upper()}", font=label, fill=fg, anchor="mm")
    body = _font(int(min(w, h) * 0.042))
    lines, line = [], ""
    for word in scene.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=body) <= w - m * 3 or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    top = cy + r * 9.5
    room = int((h * 0.66 - top) / (body.size * 1.3))
    if len(lines) > room:
        lines = lines[:room]
        lines[-1] = lines[-1].rstrip(".,;") + "…"
    for i, l in enumerate(lines):
        d.text((w / 2, top + i * body.size * 1.3), l, font=body, fill=fg, anchor="mm")
    card.save(path)


# The edit


def _trim(pcm: np.ndarray) -> np.ndarray:
    """Cuts the silence Kokoro leaves around a line, keeping a few milliseconds."""
    loud = np.flatnonzero(np.abs(pcm) > 400)
    if len(loud) == 0:
        return pcm
    keep = int(0.03 * voice.SAMPLE_RATE)
    return pcm[max(0, loud[0] - keep): loud[-1] + keep]


def render(shots: list[Shot], ratio: str, captions: str, music_mood: str, music_file: Path | None,
           sfx: bool, out: Path, progress, cancel: threading.Event):
    size = styles.FORMATS[ratio]["out"]
    portrait = size[1] > size[0]

    # Timeline: each line follows the last after a breath that depends on how the line ends.
    lines = [_trim(voice.read_wav(s.audio)) for s in shots]
    starts, durations, t = [], [], LEAD
    for shot, pcm in zip(shots, lines):
        starts.append(t)
        durations.append(len(pcm) / voice.SAMPLE_RATE)
        ends_sentence = bool(re.search(r"[.!?…।][\"'”’)]*$", shot.narration.strip()))
        t += durations[-1] + (PAUSE_SENTENCE if ends_sentence else PAUSE_CONTINUE)
    total = starts[-1] + durations[-1] + TAIL
    cuts = [0.0] + [s - CUT_EARLY for s in starts[1:]] + [total]
    slides = {k for k in range(1, len(shots)) if shots[k].stage != shots[k - 1].stage and not shots[k].shared}

    # Soundtrack.
    narration = np.zeros(int(total * voice.SAMPLE_RATE) + 1, dtype=np.int16)
    for pcm, start in zip(lines, starts):
        i = int(start * voice.SAMPLE_RATE)
        narration[i:i + len(pcm)] = pcm[: len(narration) - i]
    if music_file:
        bed = audio.load_file(music_file, total)
    elif music_mood in audio.MOODS:
        bed = audio.music(music_mood, total)
    else:
        bed = None
    effects = [(cuts[k], audio.whoosh(seed=k)) for k in sorted(slides)] if sfx else []
    mixed = audio.mix(narration, voice.SAMPLE_RATE, bed, effects)
    work = out.parent / ".render"
    work.mkdir(exist_ok=True)
    soundtrack = work / "soundtrack.wav"
    with wave.open(str(soundtrack), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(audio.RATE)
        w.writeframes(mixed.tobytes())

    # Captions, drawn once and reused.
    overlay: list[Caption] = []
    for k, shot in enumerate(shots):
        if captions == "subtitles":
            overlay += _subtitles(shot, starts[k], size, portrait)
        elif captions == "keywords" and shot.caption:
            overlay.append(_keyword(shot.caption, cuts[k] + 0.05, cuts[k + 1], size, portrait))

    # Each drawing is prepared once, when first needed (shots sharing a picture share it too).
    prepared: dict[Path, Image.Image] = {}

    def base(k: int) -> Image.Image:
        path = shots[k].image
        if path not in prepared:
            if len(prepared) >= 3:  # the current and previous shots are all a frame ever needs
                del prepared[next(iter(prepared))]
            prepared[path] = _base(Image.open(path).convert("RGB"), size)
        return prepared[path]

    black = Image.new("RGB", size)

    def picture(k: int, t: float) -> Image.Image:
        p = (t - cuts[k]) / (cuts[k + 1] - cuts[k])
        since = t - cuts[k]
        view = _view(shots[k].camera, p)
        punch = 1.0
        if k > 0 and shots[k].shared:
            # The same picture: glide from where the camera was to the new speaker, no cut.
            if since < GLIDE:
                before, e = _view(shots[k - 1].camera, 1.0), _ease_in_out(since / GLIDE)
                view = tuple(a + (b - a) * e for a, b in zip(before, view))
        elif k > 0 and k not in slides and since < PUNCH:
            punch = 1 + 0.045 * (1 - _ease_out(since / PUNCH))
        return _frame(base(k), view, size, punch)

    command = [paths.ffmpeg(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-",
               "-i", str(soundtrack), "-map", "0:v", "-map", "1:a"]
    partial = out.with_name(out.stem + ".part.mp4")
    command += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(partial)]
    log = open(paths.logs_dir() / "ffmpeg.log", "wb")
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)

    frames = int(total * FPS)
    k = 0
    try:
        for n in range(frames):
            if cancel.is_set():
                raise Cancelled()
            t = n / FPS
            while k < len(shots) - 1 and t >= cuts[k + 1]:
                k += 1
            frame = picture(k, t)
            # A stage change: the new shot pushes the old one out to the left.
            if k in slides and t - cuts[k] < SLIDE:
                p = _ease_out((t - cuts[k]) / SLIDE)
                old = picture(k - 1, t)
                offset = int(size[0] * p)
                canvas = Image.new("RGB", size)
                canvas.paste(old, (-offset, 0))
                canvas.paste(frame, (size[0] - offset, 0))
                frame = canvas
            live = [c for c in overlay if c.start <= t < c.end]
            if live:
                frame = frame.convert("RGBA")
                for c in live:
                    _draw_caption(frame, c, t)
                frame = frame.convert("RGB")
            if t > total - FADE_OUT:
                frame = Image.blend(frame, black, (t - (total - FADE_OUT)) / FADE_OUT)
            encoder.stdin.write(frame.tobytes())
            if n % FPS == 0:
                progress(n / frames)
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("Encoding the video failed. See ffmpeg.log in the logs folder.")
        partial.replace(out)
    except BaseException:
        encoder.kill()
        encoder.wait()
        partial.unlink(missing_ok=True)
        raise
    finally:
        log.close()
    return total
