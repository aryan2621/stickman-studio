"""The app talks to the core over stdin/stdout, one JSON object per line.

Requests: {"id": 1, "method": "...", "params": {...}} → {"id": 1, "ok": true, "result": ...}
or {"id": 1, "ok": false, "error": "..."}. Each request runs on its own thread, so long jobs
(planning, producing) don't block status checks or cancelling. Pushed messages carry an "event"
field: {"event": "job" | "download", "data": {...}}.
"""

import json
import os
import sys
import threading
import time
import traceback

from . import audio, cloud, models, projects, servers, share, styles, system


class Core:
    def __init__(self):
        self.out_lock = threading.Lock()
        self.studio = projects.Studio(self.emit)
        self.downloader = models.Downloader(self.emit)
        self.share = share.Share(self.emit)
        self.methods = {
            "options": lambda p: styles.options(),
            "memory": lambda p: system.memory(),
            "music_sample": lambda p: audio.sample(p["mood"]),
            "cloud_connect": lambda p: cloud.connect(p["accountId"], p["token"]),
            "cloud_disconnect": lambda p: cloud.disconnect(),
            "preview": lambda p: self.studio.preview(p["id"]),
            "status": self.status,
            "download": lambda p: self.downloader.download(p.get("ids") or models.missing()),
            "cancel_download": lambda p: self.downloader.cancel.set(),
            "set_settings": self.set_settings,
            "delete_model": lambda p: models.delete(p["id"]),
            "list_projects": lambda p: projects.summaries(),
            "get_project": lambda p: projects.view(projects.load(p["id"])),
            "create_project": lambda p: self.studio.create(p["story"], p["settings"]),
            "revise_plan": lambda p: self.studio.revise(p["id"], p.get("notes", ""), p.get("duration")),
            "update_project": lambda p: self.studio.update(p["id"], p["changes"]),
            "produce": lambda p: self.studio.produce(p["id"]),
            "redraw_shot": lambda p: self.studio.redraw(p["id"], int(p["index"])),
            "import_music": lambda p: projects.import_music(p["id"], p["path"]),
            "export_video": lambda p: projects.export_video(p["id"], p["path"]),
            "share_start": lambda p: self.share.start(*projects.video_file(p["id"])),
            "share_stop": lambda p: self.share.stop(),
            "remove_music": lambda p: projects.remove_music(p["id"]),
            "delete_project": lambda p: projects.trash(p["id"]),
            "cancel": lambda p: self.studio.stop_job(),
            "shutdown": lambda p: self.shutdown(),
        }

    def emit(self, event: str, data):
        self._send({"event": event, "data": data})

    def _send(self, message: dict):
        line = json.dumps(message)
        with self.out_lock:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, ValueError):
                pass  # the app is gone; the parent watch shuts everything down

    def status(self, _params):
        return {**models.status(self.downloader.snapshot()), "job": self.studio.busy(), "cloud": cloud.status()}

    def set_settings(self, params):
        before = models.settings()
        after = models.save_settings(params)
        if after != before:
            # The running engine may be the old model; the next request starts the new one.
            self.studio.engines.stop()
        return self.status({})

    def shutdown(self):
        self.share.stop()
        self.studio.stop_job()
        self.studio.engines.stop()

    def handle(self, request: dict):
        rid = request.get("id")
        method = self.methods.get(request.get("method"))
        try:
            if method is None:
                raise ValueError(f"Unknown method: {request.get('method')}")
            result = method(request.get("params") or {})
            self._send({"id": rid, "ok": True, "result": result})
        except Exception as e:  # noqa: BLE001 - every failure goes back to the UI as a message
            if not isinstance(e, (ValueError, RuntimeError, InterruptedError, cloud.Unavailable)):
                traceback.print_exc(file=sys.stderr)
            self._send({"id": rid, "ok": False, "error": str(e) or e.__class__.__name__})

    def run(self):
        # Clean up after an engine that crashed last time.
        servers.reap_orphans()
        # Stop an idle engine after a while so it gives its memory back.
        # If the app goes away without telling us (a crash, a force quit), stop too.
        def watch():
            parent = os.getppid()
            ticks = 0
            while True:
                time.sleep(2)
                ticks += 1
                if os.getppid() != parent:
                    self.shutdown()
                    os._exit(0)
                if ticks % 15 == 0:
                    self.studio.engines.stop_if_idle()

        threading.Thread(target=watch, daemon=True).start()
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                print(f"bad request: {line[:200]}", file=sys.stderr)
                continue
            threading.Thread(target=self.handle, args=(request,), daemon=True).start()
        # The app closed our stdin: it quit (or crashed). Never leave an engine running.
        self.shutdown()


def main():
    Core().run()
