"""The native engines: llama.cpp's server writes the plan, stable-diffusion.cpp's server draws.

Each runs as a child process on a free local port, started only when needed. Only one is kept
in memory at a time: the story model and the image model together would crowd an 18 GB Mac, and
a video uses them one after the other anyway. The story model stops as soon as a plan is written;
the image model a few minutes after its last drawing (so redrawing a few shots in a row doesn't
reload it each time). Both stop with the core.
"""

import atexit
import base64
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import cloud, models, paths

START_TIMEOUT = 180  # seconds; loading a model from a cold disk can be slow
# The image engine writes progress as it draws (a line per step). If its log stays silent this
# long, the drawing has stalled (macOS starved it of memory) and the engine is restarted. A normal
# silent stretch is ~15 s; ~150 s when the Mac throttles the GPU (a nearly empty battery). A real
# stall was silent for over ten minutes.
STALL = 300
DRAW_ATTEMPTS = 3
MEMORY_WAIT = 90  # seconds to wait for memory to come back before restarting the image engine
IDLE_STOP = 3 * 60
LLM_CONTEXT = 8192


# Extra image engine options (see the VAE note in docs/dev.md).
IMAGE_ARGS: list[str] = []


class Cancelled(Exception):
    pass


class Stalled(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _request(url: str, body: dict | None = None, timeout: float = 600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"{e.code}: {detail}") from None


SERVER_NAMES = ("llama-server", "sd-server")


def reap_orphans() -> int:
    """Stops story or image servers left behind by an engine that crashed or was force-killed
    (they keep running, holding gigabytes, with launchd as their parent). Only our own
    sidecars are touched. Returns how many were stopped."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    stopped = 0
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or parts[1] != "1":
            continue
        executable = parts[2].split(" --", 1)[0]
        name = os.path.basename(executable).removesuffix("-aarch64-apple-darwin")
        if name in SERVER_NAMES and ("binaries" in executable or "Stickman Studio" in executable or str(paths.bin_dir()) in executable):
            try:
                os.kill(int(parts[0]), signal.SIGTERM)
                stopped += 1
            except (ProcessLookupError, PermissionError, ValueError):
                pass
    return stopped


class Engines:
    def __init__(self):
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.kind: tuple | None = None  # ("llm", model id) or ("image", model id)
        self.port = 0
        self.last_used = time.monotonic()
        self.cancelled = threading.Event()
        # Cloudflare (when switched on): what failed during this job, so the rest of the job
        # stays on this Mac instead of failing again; and who to tell when it falls back.
        self.cloud_failed: set[str] = set()
        self.use_cloud = False  # the current video is made on Cloudflare
        # Whatever happens to the engine (an error, the end of a script), never leave a model running.
        atexit.register(self.stop)
        self.on_fallback = lambda kind, reason, just_this_one: None
        self.on_retry = lambda reason, attempt: None  # tells the user a drawing is being tried again
        self.used_cloud = False

    def new_job(self):
        self.cancelled.clear()
        self.cloud_failed.clear()
        self.used_cloud = False
        self.use_cloud = False

    def cloud_active(self, kind: str) -> bool:
        """Whether `kind` ("images" or "story") goes to Cloudflare now."""
        return self.use_cloud and kind not in self.cloud_failed and cloud.connected()

    def _try_cloud(self, kind: str, work):
        """Runs `work` on Cloudflare if the video is made there; returns None to use this Mac."""
        if not self.cloud_active(kind):
            return None
        try:
            result = work()
        except cloud.Refused as e:
            # Only this request: draw it here, and keep using the cloud for the rest.
            if self.cancelled.is_set():
                raise Cancelled() from None
            self.on_fallback(kind, str(e), True)
            return None
        except cloud.Unavailable as e:
            if self.cancelled.is_set():
                raise Cancelled() from None
            self.cloud_failed.add(kind)
            cloud.note_problem(kind, str(e))
            self.on_fallback(kind, str(e), False)
            return None
        cloud.note_success()
        self.used_cloud = True
        return result

    # Process management

    def _alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self):
        with self.lock:
            if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
            self.kind = None

    def stop_if_idle(self):
        with self.lock:
            if self._alive() and time.monotonic() - self.last_used > IDLE_STOP:
                self.stop()

    def interrupt(self):
        """Cancels the current job: stopping the engine ends any request it's busy with."""
        self.cancelled.set()
        self.stop()

    def _ensure(self, kind: tuple, args: list[str], name: str, ready_path: str, log_name: str):
        with self.lock:
            self.last_used = time.monotonic()
            if self._alive() and self.kind == kind:
                return
            self.stop()
            reap_orphans()
            port = _free_port()
            log = open(paths.logs_dir() / log_name, "wb")
            self.process = subprocess.Popen(
                [str(paths.sidecar(name)), *args, *self._listen_args(name, port)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
            self.kind, self.port = kind, port
            started = time.monotonic()
            while time.monotonic() - started < START_TIMEOUT:
                if self.cancelled.is_set():
                    raise Cancelled()
                if not self._alive():
                    self.process = None
                    self.kind = None
                    raise RuntimeError(f"The {'story' if kind[0] == 'llm' else 'image'} engine stopped while starting. See {log_name} in the logs folder.")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{ready_path}", timeout=2) as response:
                        if response.status == 200:
                            return
                except (urllib.error.URLError, OSError):
                    pass
                time.sleep(0.3)
            self.stop()
            raise RuntimeError("The engine took too long to start")

    @staticmethod
    def _listen_args(name: str, port: int) -> list[str]:
        if name == "llama-server":
            return ["--host", "127.0.0.1", "--port", str(port)]
        return ["--listen-ip", "127.0.0.1", "--listen-port", str(port)]

    def _call(self, path: str, body: dict, timeout: float):
        try:
            return _request(f"http://127.0.0.1:{self.port}{path}", body, timeout)
        except (urllib.error.URLError, OSError, RuntimeError) as e:
            if self.cancelled.is_set():
                raise Cancelled() from None
            raise RuntimeError(f"The engine failed: {e}") from None
        finally:
            self.last_used = time.monotonic()

    # The story model

    def chat_json(self, system: str, user: str, schema: dict, temperature=0.7, max_tokens=6000) -> dict:
        """Asks the story model for an answer forced into `schema` (llama.cpp turns the schema
        into a grammar, so the reply is always valid JSON of that shape). For a video made on
        Cloudflare, Gemma 4 26B there writes it instead, falling back to this Mac if it can't."""
        answer = self._try_cloud("story", lambda: cloud.chat_json(system, user, schema, temperature, max_tokens))
        if answer is not None:
            return answer
        story = models.settings()["story"]
        file_id = models.choice(story).files[0]
        with self.lock:
            self._ensure(
                ("llm", story),
                ["--model", str(models.path(file_id)), "--ctx-size", str(LLM_CONTEXT),
                 "--n-gpu-layers", "999", "--parallel", "1", "--jinja", "--reasoning-budget", "0"],
                "llama-server", "/health", "llama-server.log",
            )
        reply = self._call("/v1/chat/completions", {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "plan", "schema": schema}},
        }, timeout=900)
        content = reply["choices"][0]["message"]["content"]
        if reply["choices"][0].get("finish_reason") == "length":
            raise RuntimeError("The story model ran out of room before finishing the plan. Try a shorter video.")
        return json.loads(content)

    # The image model

    def draw(self, prompt: str, width: int, height: int, seed: int) -> bytes:
        """Draws one image with the chosen image model and returns it as PNG bytes: on Cloudflare
        for a video made there (the same model), otherwise or as a fallback on this Mac."""
        png = self._try_cloud("images", lambda: cloud.draw(prompt, width, height, seed))
        if png is not None:
            return png
        choice = models.choice(models.settings()["image"])
        diffusion, vae, encoder = choice.files
        body = {"prompt": prompt, "negative_prompt": "", "width": width, "height": height,
                "steps": choice.steps, "cfg_scale": 1.0, "seed": seed, "batch_size": 1}
        for attempt in range(1, DRAW_ATTEMPTS + 1):
            with self.lock:
                self._ensure(
                    ("image", choice.id),
                    ["--diffusion-model", str(models.path(diffusion)),
                     "--vae", str(models.path(vae)),
                     "--llm", str(models.path(encoder)),
                     "--diffusion-fa", "--cfg-scale", "1.0", *IMAGE_ARGS],
                    "sd-server", "/sdapi/v1/options", "sd-server.log",
                )
            try:
                reply = self._watched_call("/sdapi/v1/txt2img", body, paths.logs_dir() / "sd-server.log")
                if not reply or not reply.get("images"):
                    raise RuntimeError(f"The image engine returned no image: {str(reply)[:300]}")
                return base64.b64decode(reply["images"][0])
            except RuntimeError as e:
                if self.cancelled.is_set():
                    raise Cancelled() from None
                if attempt == DRAW_ATTEMPTS:
                    raise
                # Start over with a fresh engine, once macOS has memory to give it.
                self.stop()
                self.on_retry(str(e), attempt + 1)
                self._wait_for_memory()
        raise AssertionError("unreachable")

    def _watched_call(self, path: str, body: dict, log: Path):
        """`_call`, stopped early if the engine's log goes silent for STALL seconds."""
        result: dict = {}

        def run():
            try:
                result["reply"] = self._call(path, body, timeout=1800)
            except BaseException as e:  # noqa: BLE001 - handed to the waiting thread
                result["error"] = e

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        size, quiet_since = -1, time.monotonic()
        while worker.is_alive():
            worker.join(2)
            try:
                now = log.stat().st_size
            except OSError:
                now = size
            if now != size:
                size, quiet_since = now, time.monotonic()
            elif worker.is_alive() and time.monotonic() - quiet_since > STALL:
                self.stop()  # ends the request
                worker.join(10)
                raise Stalled("The image engine stalled (probably short of memory)")
        if "error" in result:
            raise result["error"]
        return result["reply"]

    def _wait_for_memory(self):
        """Waits (up to MEMORY_WAIT) until macOS can give the image model its memory again."""
        from . import system
        deadline = time.monotonic() + MEMORY_WAIT
        while time.monotonic() < deadline and not self.cancelled.is_set():
            try:
                if not system.memory()["low"]:
                    return
            except Exception:  # noqa: BLE001 - a failed check shouldn't block the retry
                return
            time.sleep(3)
