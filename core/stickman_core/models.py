"""The models Stickman Studio downloads once, the user's choices in Settings, and downloads.

A "choice" is what Settings shows (Story AI, Image AI); each needs one or more files.
"""

import json
import os
import threading
import urllib.request
from dataclasses import dataclass

from . import paths


@dataclass(frozen=True)
class File:
    id: str
    name: str  # file name on disk
    url: str
    size_mb: int


FILES = {
    f.id: f
    for f in [
        File("qwen3-4b-2507", "qwen3-4b-instruct-2507-q4_k_m.gguf",
             "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf", 2497),
        File("gemma-4-12b", "gemma-4-12b-it-qat-ud-q4_k_xl.gguf",
             "https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF/resolve/main/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf", 6405),
        # FLUX.2 klein reads the prompt with the original Qwen3 4B.
        File("qwen3-4b", "qwen3-4b-q4_k_m.gguf",
             "https://huggingface.co/unsloth/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf", 2497),
        File("flux2-klein-4b", "flux-2-klein-4b-q8_0.gguf",
             "https://huggingface.co/leejet/FLUX.2-klein-4B-GGUF/resolve/main/flux-2-klein-4b-Q8_0.gguf", 4302),
        File("flux2-vae", "flux2-vae.safetensors",
             "https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors", 336),
        File("kokoro", "kokoro-v1.0.onnx",
             "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx", 326),
        File("kokoro-voices", "kokoro-voices-v1.0.bin",
             "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin", 28),
    ]
}


@dataclass(frozen=True)
class Choice:
    id: str
    kind: str  # "story" | "image"
    name: str
    note: str
    files: tuple[str, ...]  # story: (model,); image: (diffusion model, vae, text encoder)
    min_ram_gb: int
    steps: int = 0  # image models: sampling steps


CHOICES = [
    Choice("qwen3-4b-2507", "story", "Qwen3 4B", "Quick (under a minute), and writes good plans.", ("qwen3-4b-2507",), 8),
    Choice("gemma-4-12b", "story", "Gemma 4 12B", "Livelier, more inventive plans that follow your notes closely. Slower.", ("gemma-4-12b",), 16),
    Choice("flux2-klein-4b", "image", "FLUX.2 klein 4B",
           "Follows the style closely: hollow heads, thin lines. About a minute a shot.",
           ("flux2-klein-4b", "flux2-vae", "qwen3-4b"), 16, steps=4),
]

# Files every setup needs whatever is chosen: the narrator's voice.
ALWAYS = ("kokoro", "kokoro-voices")

SETTINGS_FILE = "settings.json"


def ram_gb() -> int:
    try:
        return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1 << 30))
    except (ValueError, OSError):
        return 8


def path(file_id: str):
    return paths.models_dir() / FILES[file_id].name


def downloaded(file_id: str) -> bool:
    return path(file_id).exists()


def choice(choice_id: str) -> Choice:
    for c in CHOICES:
        if c.id == choice_id:
            return c
    raise ValueError(f"Unknown model: {choice_id}")


def settings() -> dict:
    defaults = {"story": "qwen3-4b-2507", "image": "flux2-klein-4b"}
    try:
        saved = json.loads((paths.data_dir() / SETTINGS_FILE).read_text())
    except (OSError, ValueError):
        saved = {}
    merged = {**defaults, **{k: v for k, v in saved.items() if k in defaults}}
    # Ignore a saved id this version no longer offers.
    for kind in ("story", "image"):
        if not any(c.id == merged[kind] and c.kind == kind for c in CHOICES):
            merged[kind] = defaults[kind]
    return merged


def save_settings(changes: dict) -> dict:
    current = settings()
    for kind in ("story", "image"):
        if kind in changes:
            if choice(changes[kind]).kind != kind:
                raise ValueError(f"{changes[kind]} isn't a {kind} model")
            current[kind] = changes[kind]
    (paths.data_dir() / SETTINGS_FILE).write_text(json.dumps(current, indent=2))
    return current


def needed() -> list[str]:
    """Every file the chosen setup uses, without duplicates, in download order."""
    s = settings()
    ids = list(ALWAYS) + list(choice(s["story"]).files) + list(choice(s["image"]).files)
    return list(dict.fromkeys(ids))


def missing() -> list[str]:
    return [f for f in needed() if not downloaded(f)]


def status(downloading: dict) -> dict:
    s = settings()
    return {
        "ramGb": ram_gb(),
        "settings": s,
        "ready": not missing(),
        "missing": [{"id": f, "sizeMb": FILES[f].size_mb} for f in missing()],
        "choices": [
            {
                "id": c.id,
                "kind": c.kind,
                "name": c.name,
                "note": c.note,
                "minRamGb": c.min_ram_gb,
                "sizeMb": sum(FILES[f].size_mb for f in c.files),
                "downloaded": all(downloaded(f) for f in c.files),
                "active": s[c.kind] == c.id,
            }
            for c in CHOICES
        ],
        "downloading": downloading,
    }


class Downloader:
    """Downloads files one at a time with progress, so a cancelled or failed download leaves no
    half-written model behind (it goes to a .part file that is renamed only when complete)."""

    def __init__(self, emit):
        self.emit = emit
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.state: dict = {}  # {"file": id, "done": MB, "total": MB, "index": n, "count": n}

    def snapshot(self) -> dict:
        return dict(self.state)

    def download(self, file_ids: list[str]):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError("A download is already running")
        try:
            self.cancel.clear()
            todo = [f for f in dict.fromkeys(file_ids) if not downloaded(f)]
            for index, file_id in enumerate(todo):
                self._one(file_id, index, len(todo))
        finally:
            self.state = {}
            self.emit("download", {})
            self.lock.release()

    def _one(self, file_id: str, index: int, count: int):
        f = FILES[file_id]
        final = path(file_id)
        part = final.with_suffix(final.suffix + ".part")
        request = urllib.request.Request(f.url, headers={"User-Agent": "StickmanStudio/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(part, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                done = reported = 0
                while chunk := response.read(1 << 20):
                    if self.cancel.is_set():
                        raise InterruptedError("Cancelled")
                    out.write(chunk)
                    done += len(chunk)
                    if done - reported >= 8 << 20 or done == total:
                        reported = done
                        self.state = {"file": file_id, "done": done >> 20, "total": total >> 20, "index": index, "count": count}
                        self.emit("download", self.state)
            if total and done != total:
                raise RuntimeError(f"The download of {f.name} was incomplete. Please try again.")
            part.rename(final)
        except BaseException:
            part.unlink(missing_ok=True)
            raise


def delete(choice_id: str):
    """Deletes a choice's files, unless the current setup still needs them."""
    keep = set(needed())
    for file_id in choice(choice_id).files:
        if file_id not in keep:
            path(file_id).unlink(missing_ok=True)
