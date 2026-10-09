"""Campaign folders: drop videos and links into EXPORT_DIR/<campaign>/, get
clips back in EXPORT_DIR/<campaign>/hotovo/ (self-host).

A campaign is any folder directly under EXPORT_DIR (other than the per-video
folders clip_export writes) holding:

    instrukce.txt   the form below; written as a template when missing
    odkazy.txt      one video URL per line (optional)
    *.mp4 ...       video files (optional)

instrukce.txt (keys are case- and accent-insensitive, "#" starts a comment):

    mam_prava: ano          required: you own the content or may clip it
    klipu: 10               1-15
    delka: 20-45            seconds, min-max
    titulky: ano
    hook: ano
    hashtagy: #tag #tag     appended to every clip's .txt
    kredit: @creator        appended to every clip's .txt

Sources run one at a time through the normal API (POST /api/process), so the
queue, the GPU guard and the pipeline are the dashboard's. A finished file is
deleted, a finished link is commented out ("# hotovo"); a failed link becomes
"# chyba" (remove the prefix to retry) and a failed file is skipped until it
is renamed or replaced. Each campaign gets a stav.txt with what is going on.
"""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request

import clip_export

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
INSTRUCTIONS = "instrukce.txt"
LINKS = "odkazy.txt"
STATUS = "stav.txt"
DONE_DIR = "hotovo"
STATE_FILE = ".openshorts-inbox.json"
# A file still being copied in keeps changing; wait until it has settled.
FILE_SETTLE_SECONDS = 30
MAX_UPLOAD_BYTES = 2048 * 1024 * 1024  # app.MAX_FILE_SIZE_MB
_EXPORT_FOLDER_RE = re.compile(r" \[[0-9a-f]{8}\]$")

TEMPLATE = """\
# Instrukce pro tuhle kampan. Radky s # jsou poznamky.
# Videa (.mp4, .mov ...) dej do teto slozky, odkazy do odkazy.txt (jeden na radek).
# Hotove klipy se objevi ve slozce hotovo.

# Potvrd, ze mas k obsahu prava nebo svoleni ho klipovat (ano/ne):
mam_prava: ne

klipu: 10
delka: 20-45
titulky: ano
hook: ano
hashtagy:
kredit:
"""


class ApiError(Exception):
    pass


# ---------------------------------------------------------------- parsing

def _norm(text):
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def _yes(value):
    return _norm(value) in ("ano", "yes", "true", "1", "a", "y")


def parse_instructions(text):
    """Return (api_fields, extras, problems) from instrukce.txt."""
    raw = {}
    for line in text.splitlines():
        # Only whole-line comments: hashtag values contain "#" themselves.
        if line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        raw[_norm(key)] = value.strip()
    fields, problems = {}, []
    if not _yes(raw.get("mam_prava", "")):
        problems.append("V instrukce.txt chybi 'mam_prava: ano'.")
    count = raw.get("klipu") or raw.get("klipy")
    if count:
        if count.isdigit() and 1 <= int(count) <= 15:
            fields["target_clips"] = int(count)
        else:
            problems.append(f"klipu: '{count}' musi byt cislo 1-15.")
    length = raw.get("delka")
    if length:
        m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", length)
        if m and 5 <= int(m.group(1)) and int(m.group(2)) <= 180 \
                and int(m.group(2)) >= int(m.group(1)) + 5:
            fields["clip_min_seconds"] = int(m.group(1))
            fields["clip_max_seconds"] = int(m.group(2))
        else:
            problems.append(f"delka: '{length}' musi byt napr. 20-45 (5-180 s, rozdil aspon 5).")
    if raw.get("titulky"):
        fields["captions"] = _yes(raw["titulky"])
    if raw.get("hook"):
        fields["auto_hook"] = _yes(raw["hook"])
    extras = {k: raw[k] for k in ("hashtagy", "kredit") if raw.get(k)}
    return fields, extras, problems


def _read_links(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return [l.strip() for l in f if l.strip().lower().startswith(("http://", "https://"))]
    except OSError:
        return []


def _mark_link(path, url, prefix):
    """Comment out a processed link: '<prefix> <url>'."""
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    out, done = [], False
    for line in lines:
        if not done and line.strip() == url:
            out.append(f"{prefix} {url}")
            done = True
        else:
            out.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


# ---------------------------------------------------------------- state

def _load_state(export_dir):
    try:
        with open(os.path.join(export_dir, STATE_FILE), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    state.setdefault("active", None)
    state.setdefault("failed_files", [])
    state.setdefault("jobs", [])
    return state


def _save_state(export_dir, state):
    path = os.path.join(export_dir, STATE_FILE)
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(path + ".part", path)


def campaign_job_ids(export_dir):
    """Job ids that belong to a campaign (clip_export leaves them alone)."""
    return set(_load_state(export_dir)["jobs"])


def _file_key(path):
    st = os.stat(path)
    return f"{os.path.basename(path)}|{st.st_size}|{int(st.st_mtime)}"


def _write_status(folder, text):
    stamp = time.strftime("%Y-%m-%d %H:%M")
    try:
        with open(os.path.join(folder, STATUS), "w", encoding="utf-8") as f:
            f.write(f"[{stamp}] {text}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- API

class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def _call(self, method, path, body=None, data=None, headers=None, timeout=60):
        if body is not None:
            data = json.dumps(body).encode()
            headers = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail")
            except Exception:
                detail = None
            raise ApiError(detail if isinstance(detail, str) else f"HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(f"backend nedostupny ({e})")

    def submit_file(self, path, fields):
        slot = self._call("POST", "/api/uploads", {"filename": os.path.basename(path)})
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            self._call("PUT", f"/api/uploads/{slot['upload_id']}", data=f,
                       headers={"Content-Length": str(size),
                                "Content-Type": "application/octet-stream"},
                       timeout=3600)
        return self._process({"upload_id": slot["upload_id"], **fields})

    def submit_url(self, url, fields):
        return self._process({"url": url, **fields})

    def _process(self, body):
        return self._call("POST", "/api/process", {"acknowledged": True, **body})["job_id"]

    def status(self, job_id):
        return self._call("GET", f"/api/status/{job_id}")


# ---------------------------------------------------------------- loop

def _campaigns(export_dir):
    for name in sorted(os.listdir(export_dir)):
        folder = os.path.join(export_dir, name)
        if (os.path.isdir(folder) and not name.startswith(".")
                and not _EXPORT_FOLDER_RE.search(name)):
            yield folder


def _pending(folder, state, now):
    """The next (kind, source) to run in this campaign, or None."""
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not (os.path.isfile(path) and name.lower().endswith(VIDEO_EXTS)):
            continue
        if now - os.path.getmtime(path) < FILE_SETTLE_SECONDS:
            continue
        if _file_key(path) in state["failed_files"]:
            continue
        return "file", path
    links = _read_links(os.path.join(folder, LINKS))
    return ("url", links[0]) if links else None


def _finish(state, export_dir, output_dir, now, api):
    """Advance the active job. Returns True while it still occupies the queue."""
    act = state["active"]
    folder = act["folder"]
    label = act["label"]
    try:
        st = api.status(act["job"])
    except ApiError as e:
        act["errors"] = act.get("errors", 0) + 1
        if act["errors"] < 20:
            return True
        return _fail(state, f"stav ulohy nejde zjistit ({e})")
    status = st.get("status")
    if status in ("queued", "processing"):
        _write_status(folder, f"Zpracovavam {label} ...")
        return True
    if status != "completed":
        logs = st.get("logs") or []
        return _fail(state, logs[-1] if logs else f"uloha skoncila: {status}")
    job_dir = os.path.join(output_dir, act["job"])
    if not os.path.isdir(job_dir) or now - clip_export._newest_write(job_dir) < clip_export.SETTLE_SECONDS:
        return True
    copied = clip_export.export_job(job_dir, os.path.join(folder, DONE_DIR), now=now)
    if not copied:
        return _fail(state, "z videa nevznikl zadny klip")
    for clip in copied:
        _append_extras(clip, act.get("extras") or {})
    if act["kind"] == "file":
        try:
            os.remove(act["source"])
        except OSError:
            pass
    else:
        try:
            _mark_link(os.path.join(folder, LINKS), act["source"], "# hotovo")
        except OSError:
            pass
    _write_status(folder, f"Hotovo: {label} ({len(copied)} klipu v {DONE_DIR}).")
    state["active"] = None
    return False


def _append_extras(clip_path, extras):
    if not extras:
        return
    txt = clip_path[:-len(".mp4")] + ".txt"
    with open(txt, "a", encoding="utf-8") as f:
        for label, key in (("Hashtagy", "hashtagy"), ("Kredit", "kredit")):
            if extras.get(key):
                f.write(f"{label}: {extras[key]}\n")


def _fail(state, reason):
    act = state["active"]
    if act["kind"] == "file":
        if act.get("key"):
            state["failed_files"].append(act["key"])
        hint = "Pro novy pokus soubor prejmenuj."
    else:
        try:
            _mark_link(os.path.join(act["folder"], LINKS), act["source"], "# chyba")
        except OSError:
            pass
        hint = "Pro novy pokus smaz '# chyba' pred odkazem v odkazy.txt."
    _write_status(act["folder"], f"Chyba u {act['label']}: {reason}\n{hint}")
    state["active"] = None
    return False


def tick(export_dir, output_dir, api, now=None):
    """One pass: advance the running job or start the next source."""
    now = time.time() if now is None else now
    if not os.path.isdir(export_dir):
        return
    state = _load_state(export_dir)
    try:
        if state["active"] and _finish(state, export_dir, output_dir, now, api):
            return
        for folder in _campaigns(export_dir):
            instr = os.path.join(folder, INSTRUCTIONS)
            if not os.path.exists(instr):
                if any(n.lower().endswith(VIDEO_EXTS) or n == LINKS for n in os.listdir(folder)):
                    with open(instr, "w", encoding="utf-8") as f:
                        f.write(TEMPLATE)
                    _write_status(folder, "Vypln instrukce.txt (hlavne 'mam_prava: ano').")
                continue
            nxt = _pending(folder, state, now)
            if not nxt:
                continue
            with open(instr, encoding="utf-8-sig") as f:
                fields, extras, problems = parse_instructions(f.read())
            if problems:
                _write_status(folder, "Ceka na instrukce: " + " ".join(problems))
                continue
            kind, source = nxt
            label = os.path.basename(source) if kind == "file" else source
            state["active"] = {"folder": folder, "kind": kind, "source": source,
                               "label": label, "extras": extras,
                               "key": _file_key(source) if kind == "file" else None}
            if kind == "file" and os.path.getsize(source) > MAX_UPLOAD_BYTES:
                _fail(state, "soubor je vetsi nez 2 GB")
                continue
            _write_status(folder, f"Odesilam {label} ...")
            try:
                job = (api.submit_file(source, fields) if kind == "file"
                       else api.submit_url(source, fields))
            except ApiError as e:
                _fail(state, str(e))
                continue
            state["active"]["job"] = job
            state["jobs"] = (state["jobs"] + [job])[-500:]
            _write_status(folder, f"Zpracovavam {label} ...")
            return
    finally:
        _save_state(export_dir, state)
