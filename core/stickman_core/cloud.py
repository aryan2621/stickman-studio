"""Cloudflare Workers AI: an optional, faster place to draw the shots and write the plan.

Workers AI runs the same FLUX.2 klein 4B the app uses locally (so cloud and local shots look
alike) and Gemma 4 26B, a far stronger story model than the local 4B. Its free tier is 10,000
"neurons" a day: a shot costs ~105–160, a plan under 100, so about 5–8 one-minute videos a day.

It's off until the user connects their own Cloudflare account, and then each video chooses where
it's made (this Mac or Cloudflare). The API token lives in the macOS Keychain, the account ID in
cloud.json. Whenever the cloud can't do the work (free allowance used up, token rejected, no
internet), the caller falls back to this Mac and tells the user why.
"""

import base64
import io
import json
import time
import urllib.error
import urllib.request
import uuid

import keyring
from PIL import Image

from . import paths

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai"
IMAGE_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"
STORY_MODEL = "@cf/google/gemma-4-26b-a4b-it"
KEYCHAIN_SERVICE = "com.stickmanstudio.app.cloudflare"
SETTINGS_FILE = "cloud.json"


class Unavailable(Exception):
    """The cloud can't do this now; `str(e)` says why, in words for the user."""


class Refused(Unavailable):
    """The cloud's safety filter blocked this one request (often a false alarm on a harmless
    scene). Only this request needs another way; the next ones can still go to the cloud."""


# Settings and credentials


def settings() -> dict:
    try:
        saved = json.loads((paths.data_dir() / SETTINGS_FILE).read_text())
    except (OSError, ValueError):
        saved = {}
    return {"accountId": saved.get("accountId", "")}


def _save(values: dict):
    (paths.data_dir() / SETTINGS_FILE).write_text(json.dumps(values, indent=2))


def _token(account: str) -> str | None:
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, account) if account else None
    except keyring.errors.KeyringError:
        return None


def connected() -> bool:
    return bool(_token(settings()["accountId"]))


def connect(account: str, token: str) -> dict:
    """Checks the account and token with Cloudflare, then saves them (the token in the Keychain)."""
    account, token = account.strip(), token.strip()
    if not account or not token:
        raise ValueError("Enter both your Cloudflare account ID and an API token")
    # Listing the AI models is free and needs the token's Workers AI permission.
    _request("GET", f"{API.format(account=account)}/models/search?per_page=1", token, None, timeout=20)
    keyring.set_password(KEYCHAIN_SERVICE, account, token)
    _save({"accountId": account})
    return status()


def disconnect():
    s = settings()
    if s["accountId"]:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, s["accountId"])
        except keyring.errors.KeyringError:
            pass
    _save({"accountId": ""})
    note_success()




# The last problem, for the status indicator (kept in memory: it's about this session).
_last_problem: dict | None = None


def note_problem(what: str, reason: str):
    global _last_problem
    _last_problem = {"what": what, "reason": reason, "at": time.time()}


def note_success():
    global _last_problem
    _last_problem = None


def status() -> dict:
    s = settings()
    return {**s, "connected": connected(), "problem": _last_problem}



# Requests


REFUSED = "Cloudflare’s safety filter blocked this picture (it often flags harmless scenes)"


def _explain(code: int, body: str) -> str:
    text = body.lower()
    if "flagged" in text or "choose another prompt" in text or "nsfw" in text:
        return REFUSED
    if code == 429 or "4006" in text or "neuron" in text and ("limit" in text or "allocation" in text):
        return "today’s free Cloudflare allowance is used up (it resets at midnight UTC)"
    if code in (401, 403) or "authentication" in text or "10000" in text:
        return "Cloudflare rejected the API token (it may have expired or lack Workers AI access)"
    if code == 404:
        return "Cloudflare couldn’t find that account ID"
    if code == 400:
        return f"Cloudflare couldn’t process this request ({body[:160].strip()})"
    if code >= 500:
        return f"Cloudflare is having trouble right now (error {code})"
    return f"Cloudflare returned error {code}"


def _request(method: str, url: str, token: str, body: bytes | None, content_type: str = "application/json", timeout: float = 120):
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "StickmanStudio/0.1"}
    if body is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        reason = _explain(e.code, e.read().decode(errors="replace"))
        raise (Refused if reason == REFUSED else Unavailable)(reason) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Unavailable(f"Cloudflare couldn’t be reached ({getattr(e, 'reason', e)})") from None
    if isinstance(reply, dict) and reply.get("success") is False:
        errors = reply.get("errors") or []
        reason = _explain(400, "; ".join(str(e.get("message", e)) for e in errors) or "unknown error")
        raise (Refused if reason == REFUSED else Unavailable)(reason)
    return reply


def _credentials() -> tuple[str, str]:
    s = settings()
    token = _token(s["accountId"])
    if not token:
        raise Unavailable("Cloudflare isn’t connected")
    return s["accountId"], token


def draw(prompt: str, width: int, height: int, seed: int) -> bytes:
    """Draws one image with FLUX.2 klein 4B on Workers AI; returns PNG bytes."""
    account, token = _credentials()
    boundary = uuid.uuid4().hex
    fields = {"prompt": prompt, "width": str(width), "height": str(height), "seed": str(seed % 2**31)}
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
    ) + f"--{boundary}--\r\n".encode()
    reply = _request("POST", f"{API.format(account=account)}/run/{IMAGE_MODEL}", token, body,
                     f"multipart/form-data; boundary={boundary}", timeout=180)
    result = reply.get("result", reply)
    encoded = result.get("image") if isinstance(result, dict) else None
    if not encoded:
        raise Unavailable("Cloudflare returned no image")
    # Normalise to PNG whatever format comes back.
    out = io.BytesIO()
    Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB").save(out, "PNG")
    return out.getvalue()


def chat_json(system: str, user: str, schema: dict, temperature: float, max_tokens: int) -> dict:
    """Asks Gemma 4 26B on Workers AI for an answer in `schema`."""
    account, token = _credentials()
    payload = {
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_schema", "json_schema": {"name": "plan", "schema": schema}},
        # The plan should come straight away, not after the model thinks out loud.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    reply = _request("POST", f"{API.format(account=account)}/run/{STORY_MODEL}", token, json.dumps(payload).encode(), timeout=300)
    result = reply.get("result", reply)
    # Workers AI answers in its own shape ({"response": ...}) or OpenAI's ({"choices": [...]}).
    content = None
    if isinstance(result, dict):
        if result.get("choices"):
            content = result["choices"][0].get("message", {}).get("content")
        elif "response" in result:
            content = result["response"]
    if isinstance(content, dict):
        return content
    if not content:
        raise Unavailable("Cloudflare’s story model gave an empty answer")
    try:
        start, end = content.index("{"), content.rindex("}") + 1
        return json.loads(content[start:end])
    except ValueError:
        raise Unavailable("Cloudflare’s story model didn’t answer in the plan format") from None
