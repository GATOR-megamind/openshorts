"""Copy finished clips out of output/ into a plain folder (self-host).

Job directories are swept after JOB_RETENTION_SECONDS, and their clips sit
among temp files, intermediate renders and every edited version. This keeps
one copy per clip, its latest version, next to a .txt with the title and
descriptions the model wrote for it, in one folder per job (per source video):

    EXPORT_DIR/<video title> [<job id>]/clip_1.mp4, clip_1.txt, ...

    python clip_export.py              # loop: OUTPUT_DIR=output EXPORT_DIR=clips
    python clip_export.py --once

A job directory is exported only once nothing in it has been written for
SETTLE_SECONDS, so a render in progress is never copied. A later edit
(subtitles, hook, effects) produces a newer file and replaces the copy.
"""
import argparse
import json
import os
import re
import shutil
import time

SETTLE_SECONDS = 45
POLL_SECONDS = 15

# Every rendered version of clip N ends in "_clip_N.mp4" (main.py names it
# "<title>_clip_N.mp4"; edits prefix subtitled_/hooked_/edited_/...).
_CLIP_RE = re.compile(r"_clip_(\d+)\.mp4$")
_SKIP_PREFIXES = ("temp_", "wm_", ".")


def _clip_groups(job_dir):
    """{clip number: [paths of every version of that clip]}."""
    groups = {}
    for name in os.listdir(job_dir):
        m = _CLIP_RE.search(name)
        if not m or name.startswith(_SKIP_PREFIXES):
            continue
        groups.setdefault(int(m.group(1)), []).append(os.path.join(job_dir, name))
    return groups


def _newest_write(job_dir):
    newest = 0.0
    for name in os.listdir(job_dir):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(job_dir, name)))
        except OSError:
            pass
    return newest


def _shorts(job_dir):
    """The model's per-clip metadata (titles, descriptions), or []."""
    for name in os.listdir(job_dir):
        if name.endswith("_metadata.json"):
            try:
                with open(os.path.join(job_dir, name), encoding="utf-8") as f:
                    return json.load(f).get("shorts") or []
            except (OSError, ValueError):
                return []
    return []


def _caption(short):
    lines = []
    for label, key in (("YouTube title", "video_title_for_youtube_short"),
                       ("TikTok", "video_description_for_tiktok"),
                       ("Instagram", "video_description_for_instagram"),
                       ("Hook", "viral_hook_text")):
        if short.get(key):
            lines.append(f"{label}: {short[key]}")
    return "\n".join(lines) + "\n" if lines else ""


def _copy_atomic(src, dest):
    tmp = dest + ".part"
    shutil.copy2(src, tmp)
    os.replace(tmp, dest)


def export_job(job_dir, export_dir, now=None):
    """Export the latest version of each clip of one job. Returns the copied paths."""
    now = time.time() if now is None else now
    if now - _newest_write(job_dir) < SETTLE_SECONDS:
        return []
    groups = _clip_groups(job_dir)
    if not groups:
        return []
    shorts = _shorts(job_dir)
    job_tag = os.path.basename(os.path.normpath(job_dir))[:8]
    # The undecorated "<title>_clip_N.mp4" is the shortest name of any clip.
    shortest = os.path.basename(min((v for vs in groups.values() for v in vs), key=len))
    title = _CLIP_RE.sub("", shortest).strip(" .") or "video"
    folder = os.path.join(export_dir, f"{title} [{job_tag}]")
    os.makedirs(folder, exist_ok=True)
    copied = []
    for number, versions in sorted(groups.items()):
        latest = max(versions, key=os.path.getmtime)
        dest = os.path.join(folder, f"clip_{number}.mp4")
        if os.path.exists(dest) and os.path.getmtime(dest) >= os.path.getmtime(latest):
            continue
        _copy_atomic(latest, dest)
        copied.append(dest)
        if 0 < number <= len(shorts) and isinstance(shorts[number - 1], dict):
            caption = _caption(shorts[number - 1])
            if caption:
                with open(dest[:-len(".mp4")] + ".txt", "w", encoding="utf-8") as f:
                    f.write(caption)
    return copied


def export_all(output_dir, export_dir, now=None):
    os.makedirs(export_dir, exist_ok=True)
    copied = []
    if not os.path.isdir(output_dir):
        return copied
    for name in sorted(os.listdir(output_dir)):
        job_dir = os.path.join(output_dir, name)
        if os.path.isdir(job_dir) and not name.startswith("."):
            try:
                copied += export_job(job_dir, export_dir, now)
            except OSError as e:
                # The cleanup sweep can remove a job mid-scan; try again next pass.
                print(f"clip_export: skipped {name}: {e}", flush=True)
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="export once and exit")
    args = parser.parse_args()
    output_dir = os.environ.get("OUTPUT_DIR", "output")
    export_dir = os.environ.get("EXPORT_DIR", "clips")
    print(f"clip_export: {output_dir} -> {export_dir}", flush=True)
    while True:
        for path in export_all(output_dir, export_dir):
            print(f"clip_export: {os.path.basename(path)}", flush=True)
        if args.once:
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
