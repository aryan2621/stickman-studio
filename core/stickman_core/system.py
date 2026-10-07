"""How much memory this Mac can give the image model right now, and who is using it.

Drawing needs the image model (~7 GB) resident. When other apps leave less than that free, macOS
swaps, and a shot that takes ~70 s can take five minutes, so the app warns before it starts.
"""

import re
import subprocess
from collections import defaultdict
from pathlib import Path

from . import models


def _sysctl(name: str) -> str:
    return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True).stdout.strip()


def available_gb() -> float:
    """Memory macOS can hand out without swapping: free pages plus those it can drop at once
    (inactive, speculative and purgeable)."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+) bytes", out).group(1))
    pages = {m.group(1): int(m.group(2)) for m in re.finditer(r"^Pages (\w[\w ]*?):\s+(\d+)\.", out, re.M)}
    reclaimable = sum(pages.get(k, 0) for k in ("free", "inactive", "speculative", "purgeable"))
    return reclaimable * page / (1 << 30)


def swap_used_gb() -> float:
    match = re.search(r"used = ([\d.]+)M", _sysctl("vm.swapusage"))
    return float(match.group(1)) / 1024 if match else 0.0


def top_apps(limit: int = 3) -> list[dict]:
    """The apps using the most memory, with all of an app's processes added together."""
    out = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True).stdout
    usage: dict[str, int] = defaultdict(int)
    for line in out.splitlines():
        rss, _, command = line.strip().partition(" ")
        if not rss.isdigit():
            continue
        # "/Applications/Brave Browser.app/Contents/Frameworks/…/Helper" → "Brave Browser"
        app = re.search(r"/([^/]+)\.app/", command)
        name = app.group(1) if app else Path(command.strip()).name
        if name in ("Stickman Studio", "sd-server", "llama-server", "stickman-core", "kernel_task", "WindowServer"):
            continue
        usage[name] += int(rss)
    ranked = sorted(usage.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"name": name, "gb": round(kb / (1 << 20), 1)} for name, kb in ranked]


def image_model_gb() -> float:
    choice = models.choice(models.settings()["image"])
    return sum(models.FILES[f].size_mb for f in choice.files) / 1000


def memory() -> dict:
    # Its working memory comes out of what macOS frees as it goes, so warn only when even the
    # weights don't fit (that's when drawing slows from ~70 s to minutes a shot).
    need = image_model_gb()
    free = available_gb()
    return {
        "availableGb": round(free, 1),
        "swapGb": round(swap_used_gb(), 1),
        "neededGb": round(need, 1),
        "low": free < need,
        "topApps": top_apps(),
    }


def battery() -> dict | None:
    """The battery's charge (%) and whether it's charging, or None on a Mac without one. A nearly
    empty battery makes macOS slow the GPU down a lot, even on the charger."""
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    match = re.search(r"(\d+)%;\s*([\w ]+?);", out)
    if not match:
        return None
    return {"percent": int(match.group(1)), "charging": match.group(2).strip() in ("charging", "charged", "finishing charge")}
