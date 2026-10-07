"""Videos ("projects"): each is a folder with project.json, the drawn shots, the narration and the
final MP4. Work is incremental: every shot remembers the inputs its image and audio were made
from, so after an edit only the changed shots are drawn or spoken again.
"""

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import cloud, models, paths, planner, render, styles, system, voice
from .servers import Cancelled, Engines

PROJECT_FILE = "project.json"
PREVIEW_FILE = "preview.mp4"
# Bump when the edit itself changes (cuts, captions, mix), so existing videos offer an update.
RENDER_VERSION = 4
SHOT_FIELDS = ("narration", "scene", "camera", "caption", "speaker", "samePicture")
CLOUD_DRAWS_AT_ONCE = 4  # Cloudflare draws several shots side by side; this Mac draws one at a time


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12]


def _folder(project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9-]+", project_id):
        raise ValueError("Bad project id")
    folder = paths.projects_dir() / project_id
    if not (folder / PROJECT_FILE).exists():
        raise ValueError("This video no longer exists")
    return folder


def load(project_id: str) -> dict:
    return json.loads((_folder(project_id) / PROJECT_FILE).read_text())


def save(project: dict) -> dict:
    project["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    folder = paths.projects_dir() / project["id"]
    temp = folder / (PROJECT_FILE + ".tmp")
    temp.write_text(json.dumps(project, indent=2))
    temp.replace(folder / PROJECT_FILE)
    return project


def _source(shots: list[dict], i: int) -> int:
    """The shot whose drawing shot `i` shows: itself, or the one it shares its picture with."""
    while i > 0 and shots[i].get("samePicture"):
        i -= 1
    return i


def _voice_for(project: dict, shot: dict) -> str:
    """The voice that reads a shot's line: its character's, or the narrator's."""
    speaker = shot.get("speaker")
    if speaker and speaker != styles.NARRATOR:
        for c in project["plan"].get("characters", []):
            if c["name"] == speaker and c.get("voice") in styles.VOICES:
                return c["voice"]
    return project["settings"]["voice"]


def _image_key(project: dict, shot: dict) -> str:
    s = project["settings"]
    parts = [s["style"], s["ratio"], shot["scene"], project["seed"], shot.get("variant", 0), models.settings()["image"]]
    cast = styles.cast_in(shot["scene"], project["plan"].get("characters", []))
    if cast:
        parts.append([{"name": c["name"], "look": c["look"]} for c in cast])  # a character's look is part of the drawing (their voice isn't)
    changed = styles.looks_in(shot["scene"], project["plan"].get("characters", []), shot.get("looks"))
    if changed:
        parts.append(changed)  # so is a look that changed earlier in the story
    if s.get("engine") == "cloud":
        parts.append("cloud")  # moving a video between this Mac and the cloud redraws its shots there
    return _key(*parts)


def _audio_key(project: dict, shot: dict) -> str:
    s = project["settings"]
    return _key(_voice_for(project, shot), s.get("speed", 1.0), shot["narration"])


def _video_key(project: dict) -> str:
    s = project["settings"]
    all_shots = project["plan"]["shots"]
    shots = [(all_shots[_source(all_shots, i)].get("imageKey"), sh.get("audioKey"), sh["camera"], sh["caption"], sh["stage"], bool(sh.get("samePicture")))
             for i, sh in enumerate(all_shots)]
    return _key(shots, s["ratio"], s["captions"], s.get("music"), s.get("musicMood"), s.get("sfx"), RENDER_VERSION)


def view(project: dict) -> dict:
    """The project as the UI sees it: with absolute media paths and what's out of date."""
    folder = paths.projects_dir() / project["id"]
    shots = []
    plan_shots = project["plan"]["shots"] if project.get("plan") else []
    for i, shot in enumerate(plan_shots):
        pic = plan_shots[_source(plan_shots, i)]
        image_ok = pic.get("image") and pic.get("imageKey") == _image_key(project, pic) and (folder / pic["image"]).exists()
        audio_ok = shot.get("audio") and shot.get("audioKey") == _audio_key(project, shot) and (folder / shot["audio"]).exists()
        shots.append({
            **{k: shot[k] for k in ("stage", "narration", "scene", "camera", "caption")},
            "speaker": shot.get("speaker") or styles.NARRATOR,
            "samePicture": bool(shot.get("samePicture")) and i > 0,
            "image": str(folder / pic["image"]) if pic.get("image") and (folder / pic["image"]).exists() else None,
            "imageStale": not image_ok,
            "audioStale": not audio_ok,
            "seconds": shot.get("seconds"),
        })
    video = folder / project["video"] if project.get("video") else None
    has_video = bool(video and video.exists())
    preview = folder / PREVIEW_FILE
    # A preview is only worth showing while it's newer than the finished video.
    has_preview = preview.exists() and (not has_video or preview.stat().st_mtime > video.stat().st_mtime)
    drawn = sum(1 for sh in shots if sh["image"] and not sh["imageStale"])
    return {
        **{k: project.get(k) for k in ("id", "createdAt", "updatedAt", "story", "settings", "seed")},
        # Some shots were drawn but the video was never finished (the app quit, or it was cancelled).
        "drawn": drawn,
        "unfinished": 0 < drawn < len(shots) or (drawn == len(shots) and len(shots) > 0 and not has_video and not has_preview),
        "folder": str(folder),
        "title": project["plan"]["title"] if project.get("plan") else "Untitled",
        "message": project["plan"]["message"] if project.get("plan") else "",
        "characters": project["plan"].get("characters", []) if project.get("plan") else [],
        "shots": shots,
        "video": str(video) if has_video else None,
        "preview": str(preview) if has_preview else None,
        "videoSeconds": project.get("videoSeconds"),
        # A line or picture that must be made again (a character's new voice) makes the video stale too.
        "videoStale": not has_video or project.get("videoKey") != _video_key(project)
        or any(sh["audioStale"] or sh["imageStale"] for sh in shots),
        "music": str(folder / project["settings"]["music"]) if project["settings"].get("music") else None,
    }


def summaries() -> list[dict]:
    items = []
    for file in paths.projects_dir().glob(f"*/{PROJECT_FILE}"):
        try:
            p = json.loads(file.read_text())
        except (OSError, ValueError):
            continue
        thumb = next((file.parent / s["image"] for s in (p.get("plan") or {}).get("shots", []) if s.get("image")), None)
        video = file.parent / p["video"] if p.get("video") else None
        try:
            v = view(p)
            unfinished, drawn = v["unfinished"], v["drawn"]
        except Exception:  # an old or damaged project shouldn't hide the rest
            unfinished, drawn = False, 0
        items.append({
            "unfinished": unfinished,
            "drawn": drawn,
            "shots": len((p.get("plan") or {}).get("shots", [])),
            "id": p["id"],
            "title": (p.get("plan") or {}).get("title", "Untitled"),
            "updatedAt": p.get("updatedAt"),
            "settings": p["settings"],
            "thumbnail": str(thumb) if thumb and thumb.exists() else None,
            "hasVideo": bool(video and video.exists()),
        })
    return sorted(items, key=lambda i: i["updatedAt"] or "", reverse=True)


def _check_settings(settings: dict) -> dict:
    s = {
        "ratio": settings.get("ratio", "9:16"),
        "duration": int(settings.get("duration", 60)),
        "style": settings.get("style", "classic-light"),
        "voice": settings.get("voice", "af_heart"),
        "speed": float(settings.get("speed", 1.0)),
        "captions": settings.get("captions", "subtitles"),
        "music": settings.get("music"),
        "musicMood": settings.get("musicMood", "curious"),
        "sfx": bool(settings.get("sfx", True)),
        "engine": settings.get("engine", "local"),
        "mode": settings.get("mode", "auto"),
        "language": settings.get("language", "en"),
        "telling": settings.get("telling", "narrator"),
    }
    if s["language"] not in styles.LANGUAGES:
        raise ValueError("Unknown language")
    if s["telling"] not in styles.TELLING:
        raise ValueError("Unknown way of telling")
    # The narrator speaks the video's language (Hindi voices can't read English and back).
    if s["voice"] in styles.VOICES and styles.VOICES[s["voice"]]["lang"] != s["language"]:
        s["voice"] = styles.default_voice(s["language"])
    if s["mode"] not in planner.MODES:
        raise ValueError("Unknown template")
    if s["engine"] not in ("local", "cloud"):
        raise ValueError("Choose this Mac or the cloud")
    if s["captions"] == "both":  # older videos: one kind of caption at a time reads better
        s["captions"] = "subtitles"
    if s["ratio"] not in styles.FORMATS:
        raise ValueError("Unknown format")
    if s["style"] not in styles.STYLES and s["style"] != "auto":
        raise ValueError("Unknown style")
    if s["voice"] not in styles.VOICES:
        raise ValueError("Unknown voice")
    if s["musicMood"] not in styles.MUSIC:
        raise ValueError("Unknown music")
    if s["captions"] not in ("subtitles", "keywords", "off"):
        raise ValueError("Unknown caption mode")
    if not 10 <= s["duration"] <= 300:
        raise ValueError("Pick a length between 10 seconds and 5 minutes")
    s["speed"] = min(1.3, max(0.8, s["speed"]))
    return s


class Studio:
    """Runs one job at a time (planning, producing, redrawing), with progress events."""

    def __init__(self, emit):
        self.emit = emit
        self.engines = Engines()
        self.engines.on_fallback = self._cloud_fallback
        self.engines.on_retry = self._draw_retry
        self.job_lock = threading.Lock()
        self.cancel = threading.Event()
        self.current: dict | None = None

    def _cloud_fallback(self, kind: str, reason: str, just_this_one: bool = False):
        what = "drawing" if kind == "images" else "planning"
        if just_this_one and kind == "images" and self.current and "shot" in self.current:
            what = f"drawing of shot {self.current['shot'] + 1}"
        self.emit("notice", {"kind": "cloud-fallback", "what": what, "reason": reason, "justThisOne": just_this_one})
        # Correct the progress line that said "in the cloud".
        if self.current and "in the cloud" in (self.current.get("message") or ""):
            c = self.current
            extra = {"shot": c["shot"]} if "shot" in c else {}
            self._progress(c["project"], c["kind"], c["message"].replace("in the cloud", "on this Mac"), c.get("done", 0), c.get("total", 0), **extra)

    def _draw_retry(self, reason: str, attempt: int):
        """A drawing failed or stalled; the engine restarts and tries again. Say so in the progress line."""
        c = self.current or {}
        if c.get("kind") != "images":
            return
        what = f"shot {c['shot'] + 1}" if "shot" in c else "a shot"
        extra = {"shot": c["shot"]} if "shot" in c else {}
        self._progress(c["project"], "images", f"Drawing {what} again (try {attempt} of 3): the image engine stalled, restarting it",
                       c.get("done", 0), c.get("total", 0), **extra)

    @staticmethod
    def _slow_note() -> str:
        """Why drawing may be slow right now, for the progress line."""
        try:
            b = system.battery()
        except Exception:  # noqa: BLE001 - only a hint
            return ""
        if b and b["percent"] < 10:
            return f" · battery at {b['percent']}%: macOS slows drawing a lot until it charges"
        return ""

    def busy(self) -> dict | None:
        return self.current

    def _job(self, project_id: str | None, kind: str, work):
        if not self.job_lock.acquire(blocking=False):
            raise RuntimeError("Another video is being worked on. Wait for it to finish or cancel it.")
        self.cancel.clear()
        self.engines.new_job()
        self.current = {"project": project_id, "kind": kind}
        # Keep the Mac from idle-sleeping mid-job (the display may still sleep). Tied to this
        # process, so it ends with the core even if the core is killed.
        awake = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            return work()
        except (Cancelled, render.Cancelled):
            raise RuntimeError("Cancelled") from None
        finally:
            awake.terminate()
            self.current = None
            self.emit("job", {"project": project_id, "stage": "idle"})
            self.job_lock.release()

    def _progress(self, project_id, stage, message, done=0, total=0, **extra):
        self.current = {"project": project_id, "kind": stage, "message": message, "done": done, "total": total, **extra}
        self.emit("job", {"project": project_id, "stage": stage, "message": message, "done": done, "total": total, **extra})

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def stop_job(self):
        self.cancel.set()
        self.engines.interrupt()

    # Planning

    def create(self, story: str, settings: dict) -> dict:
        story = story.strip()
        if len(story) < 3:
            raise ValueError("Write a story, a topic or some notes first")
        settings = _check_settings(settings)
        if models.missing():
            raise RuntimeError("Download the models first")
        project_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{random.randint(100, 999)}"

        def work():
            self.engines.use_cloud = settings["engine"] == "cloud"
            where = " in the cloud" if self.engines.cloud_active("story") else ""
            self._progress(project_id, "plan", f"Writing the director's plan{where}…")
            try:
                plan = planner.write_plan(self.engines, story, settings)
            finally:
                self.engines.stop()  # the plan is written: give the story model's memory back
            self._check()
            if "style" in plan:  # "Auto": the director chose the style
                settings["style"] = plan.pop("style")
            folder = paths.projects_dir() / project_id
            folder.mkdir(parents=True)
            now = datetime.now().isoformat(timespec="seconds")
            project = {"id": project_id, "createdAt": now, "story": story, "settings": settings,
                       "seed": random.randint(1, 2**31 - 1), "plan": plan, "video": None}
            return view(save(project))

        return self._job(project_id, "plan", work)

    def revise(self, project_id: str, notes: str, duration: int | None = None) -> dict:
        """Rewrites the plan following the user's notes. A new length rewrites it from the source
        (a 60-second plan can't simply be stretched into three minutes)."""
        def work():
            project = load(project_id)
            settings = dict(project["settings"])
            new_length = duration is not None and int(duration) != settings["duration"]
            if new_length:
                settings = _check_settings({**settings, "duration": int(duration)})
            self.engines.use_cloud = settings.get("engine") == "cloud"
            self._progress(project_id, "plan", "Rewriting the plan…")
            try:
                if new_length:
                    source = project["story"] + (f"\n\nNotes for this version: {notes.strip()}" if notes.strip() else "")
                    plan = planner.write_plan(self.engines, source, settings)
                else:
                    plan = planner.write_plan(self.engines, project["story"], settings, project["plan"], notes)
            finally:
                self.engines.stop()
            self._check()
            plan.pop("style", None)
            project["plan"] = plan
            project["settings"] = settings
            return view(save(project))

        return self._job(project_id, "plan", work)

    def update(self, project_id: str, changes: dict) -> dict:
        """Saves edits from the plan screen: title, shots (edited, added, removed, moved) and settings."""
        if self.current and self.current.get("project") == project_id:
            raise RuntimeError("Wait for the current step to finish before editing")
        project = load(project_id)
        if "settings" in changes:
            project["settings"] = _check_settings({**project["settings"], **changes["settings"]})
        if "title" in changes:
            project["plan"]["title"] = str(changes["title"]).strip() or project["plan"]["title"]
        if "shots" in changes:
            old = project["plan"]["shots"]
            shots = []
            for edited in changes["shots"]:
                # Keep the media of a shot that is still there (matched by where it came from).
                src = edited.get("from")
                base = dict(old[src]) if isinstance(src, int) and 0 <= src < len(old) else {"stage": shots[-1]["stage"] if shots else "hook"}
                for field in SHOT_FIELDS:
                    if field not in edited:
                        continue
                    if field == "samePicture":
                        base[field] = bool(edited[field]) and bool(shots)
                    elif field == "caption":
                        base[field] = str(edited[field]).strip()
                    else:
                        base[field] = " ".join(str(edited[field]).split())
                if base.get("camera") not in styles.CAMERA_MOVES:
                    base["camera"] = "push_in"
                if not base.get("narration") or not base.get("scene"):
                    raise ValueError(f"Shot {len(shots) + 1} needs both narration and a scene")
                shots.append(base)
            if not shots:
                raise ValueError("A video needs at least one shot")
            if shots[0].get("samePicture"):
                shots[0]["samePicture"] = False  # the first shot has nothing to share with
            project["plan"]["shots"] = shots
        if "characters" in changes:
            voices = {c.get("name"): c.get("voice") for c in changes["characters"] if isinstance(c, dict)}
            for c in project["plan"].get("characters", []):
                voice_id = voices.get(c["name"])
                if voice_id is not None:
                    if voice_id not in styles.VOICES:
                        raise ValueError("Unknown voice")
                    c["voice"] = voice_id
        if "settings" in changes or "characters" in changes:
            # Characters keep voices in the video's language (after a change of language too).
            s = project["settings"]
            project["plan"]["characters"] = styles.cast_voices(project["plan"].get("characters", []), s["voice"], s["language"])
        return view(save(project))

    # Production

    def produce(self, project_id: str) -> dict:
        def work():
            project = load(project_id)
            folder = paths.projects_dir() / project_id
            (folder / "voice").mkdir(exist_ok=True)
            (folder / "shots").mkdir(exist_ok=True)

            self.engines.use_cloud = project["settings"].get("engine") == "cloud"

            # 1. Narration (quick, on the CPU).
            self._record_voice(project, folder)

            # 2. Drawings (the slow part, on the GPU).
            self._draw_stale(project, folder)

            # 3. The video.
            self._render(project, folder)
            return view(project)

        return self._job(project_id, "produce", work)

    def preview(self, project_id: str) -> dict:
        """The video with sketch cards in place of shots not drawn yet: the voice, timing, cuts,
        captions and music in about a minute, before the drawings take their twenty."""
        def work():
            project = load(project_id)
            folder = paths.projects_dir() / project_id
            (folder / "voice").mkdir(exist_ok=True)
            self._record_voice(project, folder)
            s = project["settings"]
            sketches = folder / ".render" / "sketches"
            sketches.mkdir(parents=True, exist_ok=True)
            shots = []
            plan_shots = project["plan"]["shots"]
            for i, sh in enumerate(plan_shots):
                j = _source(plan_shots, i)
                pic = plan_shots[j]
                drawn = pic.get("imageKey") == _image_key(project, pic) and (folder / pic.get("image", "")).is_file()
                image = folder / pic["image"] if drawn else sketches / f"{j + 1:02d}.png"
                if not drawn and j == i:
                    render.sketch_card(image, s["style"], s["ratio"], i, sh["stage"], sh["scene"])
                shots.append(render.Shot(image, folder / sh["audio"], sh["seconds"], sh["camera"], sh["caption"], sh["narration"], sh["stage"], j != i,
                                         s.get("language", "en")))
            self._progress(project_id, "render", "Putting the preview together…", 0, 100)
            render.render(
                shots, s["ratio"], "subtitles" if s["captions"] == "both" else s["captions"], s.get("musicMood", "curious"),
                folder / s["music"] if s.get("music") else None, s.get("sfx", True), folder / PREVIEW_FILE,
                lambda p: self._progress(project_id, "render", "Putting the preview together…", round(p * 100), 100),
                self.cancel,
            )
            shutil.rmtree(sketches, ignore_errors=True)
            return view(project)

        return self._job(project_id, "preview", work)

    def _record_voice(self, project: dict, folder: Path):
        shots = project["plan"]["shots"]
        s = project["settings"]
        for i, shot in enumerate(shots):
            self._check()
            key = _audio_key(project, shot)
            if shot.get("audioKey") == key and (folder / shot.get("audio", "")).is_file():
                continue
            self._progress(project["id"], "voice", f"Recording line {i + 1} of {len(shots)}", i, len(shots))
            name = f"voice/{i + 1:02d}-{key}.wav"
            shot["seconds"] = round(voice.speak(shot["narration"], _voice_for(project, shot), s.get("speed", 1.0), folder / name), 3)
            self._replace(folder, shot, "audio", name)
            shot["audioKey"] = key
            save(project)

    def redraw(self, project_id: str, index: int) -> dict:
        """Draws one shot again with a new variation."""
        def work():
            project = load(project_id)
            folder = paths.projects_dir() / project_id
            self.engines.use_cloud = project["settings"].get("engine") == "cloud"
            index = _source(project["plan"]["shots"], index)  # a shared picture is redrawn at its first shot
            shot = project["plan"]["shots"][index]
            shot["variant"] = shot.get("variant", 0) + 1
            (folder / "shots").mkdir(exist_ok=True)
            self._draw(project, folder, index, 0, 1)
            return view(save(project))

        return self._job(project_id, "images", work)

    def _draw_stale(self, project: dict, folder: Path):
        shots = project["plan"]["shots"]
        # A shot that shares the previous picture isn't drawn: only the camera moves.
        stale = [i for i, sh in enumerate(shots) if _source(shots, i) == i
                 and (sh.get("imageKey") != _image_key(project, sh) or not (folder / sh.get("image", "")).is_file())]
        if len(stale) > 1 and self.engines.cloud_active("images"):
            self._draw_in_parallel(project, folder, stale)
            return
        for n, i in enumerate(stale):
            self._draw(project, folder, i, n, len(stale))

    def _draw_in_parallel(self, project: dict, folder: Path, stale: list[int]):
        """Cloudflare draws several shots at once; each is saved as soon as it arrives. A shot the
        cloud can't draw falls back to this Mac inside `engines.draw`, one at a time."""
        total = len(stale)
        self._progress(project["id"], "images", f"Drawing {total} shots in the cloud", 0, total)
        lock = threading.Lock()
        done = 0
        pool = ThreadPoolExecutor(max_workers=CLOUD_DRAWS_AT_ONCE)
        futures = {pool.submit(self._picture, project, i): i for i in stale}
        try:
            for future in as_completed(futures):
                i = futures[future]
                png, seconds = future.result()
                with lock:
                    self._check()
                    self._store(project, folder, i, png, seconds)
                    done += 1
                    where = " in the cloud" if self.engines.cloud_active("images") else ""
                    self._progress(project["id"], "images", f"Drawing shots{where} ({done} of {total})", done, total)
        finally:
            # On cancel or an error, don't wait for drawings still on their way.
            pool.shutdown(wait=False, cancel_futures=True)

    def _picture(self, project: dict, i: int) -> tuple[bytes, float]:
        """Draws shot `i` and returns the PNG and how long it took."""
        self._check()
        shot = project["plan"]["shots"][i]
        s = project["settings"]
        width, height = styles.FORMATS[s["ratio"]]["draw"]
        seed = (project["seed"] + shot.get("variant", 0) * 7919) % (2**31)
        started = time.monotonic()
        prompt = styles.image_prompt(s["style"], shot["scene"], project["plan"].get("characters", []), shot.get("looks"))
        return self.engines.draw(prompt, width, height, seed), time.monotonic() - started

    def _draw(self, project: dict, folder: Path, i: int, n: int, total: int):
        self._check()
        where = " in the cloud" if self.engines.cloud_active("images") else ""
        note = "" if where else self._slow_note()
        self._progress(project["id"], "images", f"Drawing shot {i + 1}{where}" + (f" ({n + 1} of {total})" if total > 1 else "") + note, n, total, shot=i)
        png, seconds = self._picture(project, i)
        self._store(project, folder, i, png, seconds)

    def _store(self, project: dict, folder: Path, i: int, png: bytes, seconds: float):
        shot = project["plan"]["shots"][i]
        key = _image_key(project, shot)
        name = f"shots/{i + 1:02d}-{key}.png"
        (folder / name).write_bytes(png)
        self._replace(folder, shot, "image", name)
        shot["imageKey"] = key
        save(project)
        self.emit("job", {"project": project["id"], "stage": "shot", "shot": i, "image": str(folder / name),
                          "seconds": round(seconds, 1)})

    def _render(self, project: dict, folder: Path):
        self._check()
        if project.get("videoKey") == _video_key(project) and project.get("video") and (folder / project["video"]).is_file():
            return
        # The image model isn't needed any more; give its memory back before encoding.
        self.engines.stop()
        s = project["settings"]
        plan_shots = project["plan"]["shots"]
        shots = []
        for i, sh in enumerate(plan_shots):
            j = _source(plan_shots, i)
            shots.append(render.Shot(folder / plan_shots[j]["image"], folder / sh["audio"], sh["seconds"], sh["camera"], sh["caption"],
                                     sh["narration"], sh["stage"], j != i, s.get("language", "en")))
        # Only what a file name can't hold goes (Hindi's vowel signs aren't "\w", so keep them).
        title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", project["plan"]["title"]).strip()[:60] or "Stickman video"
        name = f"{title}.mp4"
        self._progress(project["id"], "render", "Putting the video together…", 0, 100)
        seconds = render.render(
            shots, s["ratio"], "subtitles" if s["captions"] == "both" else s["captions"], s.get("musicMood", "curious"), folder / s["music"] if s.get("music") else None,
            s.get("sfx", True), folder / name,
            lambda p: self._progress(project["id"], "render", "Putting the video together…", round(p * 100), 100),
            self.cancel,
        )
        if project.get("video") and project["video"] != name:
            (folder / project["video"]).unlink(missing_ok=True)
        project["video"] = name
        project["videoSeconds"] = round(seconds, 1)
        (folder / PREVIEW_FILE).unlink(missing_ok=True)
        project["videoKey"] = _video_key(project)
        save(project)

    @staticmethod
    def _replace(folder: Path, shot: dict, field: str, name: str):
        """Points the shot at its new file and deletes the old one."""
        old = shot.get(field)
        shot[field] = name
        if old and old != name:
            (folder / old).unlink(missing_ok=True)


def video_file(project_id: str) -> tuple[Path, str]:
    """The finished video's file and its title (for sharing)."""
    project = load(project_id)
    folder = paths.projects_dir() / project_id
    if not project.get("video") or not (folder / project["video"]).exists():
        raise ValueError("Make the video first")
    return folder / project["video"], project["plan"]["title"]


def export_video(project_id: str, destination: str) -> str:
    """Saves a copy of the finished video where the user chose (for "Download")."""
    project = load(project_id)
    folder = paths.projects_dir() / project_id
    video = folder / project["video"] if project.get("video") else None
    if not video or not video.exists():
        raise ValueError("Make the video first")
    target = Path(destination)
    if target.suffix.lower() != ".mp4":
        target = target.with_suffix(".mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    shutil.copyfile(video, partial)
    partial.replace(target)
    return str(target)


def import_music(project_id: str, source: str) -> dict:
    src = Path(source)
    if not src.is_file():
        raise ValueError("That file can't be found")
    if src.suffix.lower() not in (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg"):
        raise ValueError("Choose an audio file (MP3, M4A, WAV, FLAC or OGG)")
    project = load(project_id)
    folder = paths.projects_dir() / project_id
    for old in folder.glob("music.*"):
        old.unlink()
    name = f"music{src.suffix.lower()}"
    shutil.copyfile(src, folder / name)
    project["settings"]["music"] = name
    return view(save(project))


def remove_music(project_id: str) -> dict:
    project = load(project_id)
    folder = paths.projects_dir() / project_id
    for old in folder.glob("music.*"):
        old.unlink()
    project["settings"]["music"] = None
    return view(save(project))


def trash(project_id: str):
    """Moves the video's folder to the Trash (it can be put back from there)."""
    folder = _folder(project_id)
    bin_ = Path.home() / ".Trash"
    target = bin_ / folder.name
    n = 2
    while target.exists():
        target = bin_ / f"{folder.name} {n}"
        n += 1
    shutil.move(str(folder), str(target))
