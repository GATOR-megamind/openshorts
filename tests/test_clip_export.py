import json
import os

import clip_export


def _touch(path, mtime, data=b"x"):
    with open(path, "wb") as f:
        f.write(data)
    os.utime(path, (mtime, mtime))


def _job(tmp_path, job_id="abcdef1234", t=1000.0):
    job = tmp_path / "output" / job_id
    job.mkdir(parents=True)
    _touch(job / "Talk.mp4", t)  # the source, not a clip
    _touch(job / "Talk_clip_1.mp4", t, b"raw1")
    _touch(job / "subtitled_9_hooked_8_Talk_clip_1.mp4", t + 5, b"final1")
    _touch(job / "Talk_clip_2.mp4", t, b"raw2")
    _touch(job / "temp_Talk_clip_3.mp4", t)
    with open(job / "Talk_metadata.json", "w") as f:
        json.dump({"shorts": [{"video_title_for_youtube_short": "First",
                               "viral_hook_text": "Wait for it"},
                              {"video_description_for_tiktok": "Second #fyp"}]}, f)
    os.utime(job / "Talk_metadata.json", (t, t))
    return job


def test_exports_latest_version_of_each_clip(tmp_path):
    _job(tmp_path)
    out = tmp_path / "clips"
    copied = clip_export.export_all(str(tmp_path / "output"), str(out), now=2000)
    folder = out / "Talk [abcdef12]"
    assert sorted(copied) == [str(folder / "clip_1.mp4"), str(folder / "clip_2.mp4")]
    assert (folder / "clip_1.mp4").read_bytes() == b"final1"
    assert (folder / "clip_2.mp4").read_bytes() == b"raw2"
    txt = (folder / "clip_1.txt").read_text()
    assert "YouTube title: First" in txt and "Hook: Wait for it" in txt
    assert "TikTok: Second #fyp" in (folder / "clip_2.txt").read_text()


def test_job_still_rendering_is_not_exported(tmp_path):
    _job(tmp_path, t=1000.0)
    out = tmp_path / "clips"
    assert clip_export.export_all(str(tmp_path / "output"), str(out), now=1010) == []


def test_second_pass_copies_nothing_until_a_newer_edit(tmp_path):
    job = _job(tmp_path)
    out = tmp_path / "clips"
    clip_export.export_all(str(tmp_path / "output"), str(out), now=2000)
    assert clip_export.export_all(str(tmp_path / "output"), str(out), now=2100) == []
    _touch(job / "edited_Talk_clip_2.mp4", 3000, b"edit2")
    copied = clip_export.export_all(str(tmp_path / "output"), str(out), now=4000)
    assert copied == [str(out / "Talk [abcdef12]" / "clip_2.mp4")]
    assert (out / "Talk [abcdef12]" / "clip_2.mp4").read_bytes() == b"edit2"


def test_each_job_gets_its_own_folder(tmp_path):
    _job(tmp_path, job_id="aaaaaaaa11")
    _job(tmp_path, job_id="bbbbbbbb22")
    out = tmp_path / "clips"
    clip_export.export_all(str(tmp_path / "output"), str(out), now=2000)
    assert sorted(os.listdir(out)) == ["Talk [aaaaaaaa]", "Talk [bbbbbbbb]"]


def test_missing_output_dir_is_fine(tmp_path):
    assert clip_export.export_all(str(tmp_path / "nope"), str(tmp_path / "clips")) == []
