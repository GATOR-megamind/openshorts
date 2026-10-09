import json
import os

import campaign_inbox as ci
import clip_export


class FakeApi:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.submitted = []
        self.statuses = {}
        self.fail_submit = None

    def _new_job(self, source, fields):
        if self.fail_submit:
            raise ci.ApiError(self.fail_submit)
        job = f"{len(self.submitted) + 1:08d}abcd"
        self.submitted.append((source, fields))
        self.statuses[job] = {"status": "processing"}
        return job

    def submit_file(self, path, fields):
        return self._new_job(path, fields)

    def submit_url(self, url, fields):
        return self._new_job(url, fields)

    def status(self, job):
        return self.statuses[job]

    def finish(self, job, t, clips=2):
        d = os.path.join(self.output_dir, job)
        os.makedirs(d)
        for i in range(1, clips + 1):
            p = os.path.join(d, f"Stream_clip_{i}.mp4")
            with open(p, "wb") as f:
                f.write(b"clip")
            os.utime(p, (t, t))
        meta = os.path.join(d, "Stream_metadata.json")
        with open(meta, "w") as f:
            json.dump({"shorts": [{"video_title_for_youtube_short": f"T{i}"}
                                  for i in range(1, clips + 1)]}, f)
        os.utime(meta, (t, t))
        self.statuses[job] = {"status": "completed"}


GOOD = "mam_prava: ano\nklipu: 5\ndelka: 20-45\ntitulky: ne\nhook: ano\nhashtagy: #irl #fyp\nkredit: @marlon\n"


def _setup(tmp_path, instructions=GOOD, video=True, links=()):
    clips = tmp_path / "clips"
    camp = clips / "Marlon"
    camp.mkdir(parents=True)
    out = tmp_path / "output"
    out.mkdir()
    if instructions is not None:
        (camp / "instrukce.txt").write_text(instructions, encoding="utf-8")
    if video:
        v = camp / "stream1.mp4"
        v.write_bytes(b"video")
        os.utime(v, (100, 100))
    if links:
        (camp / "odkazy.txt").write_text("\n".join(links) + "\n", encoding="utf-8")
    return clips, camp, out, FakeApi(str(out))


def test_parse_instructions():
    fields, extras, problems = ci.parse_instructions(GOOD)
    assert problems == []
    assert fields == {"target_clips": 5, "clip_min_seconds": 20, "clip_max_seconds": 45,
                      "captions": False, "auto_hook": True}
    assert extras == {"hashtagy": "#irl #fyp", "kredit": "@marlon"}


def test_parse_instructions_requires_rights_and_valid_values():
    _, _, problems = ci.parse_instructions("mam_prava: ne\nklipu: 40\ndelka: 30-20\n")
    assert len(problems) == 3


def test_file_runs_end_to_end_and_original_is_deleted(tmp_path):
    clips, camp, out, api = _setup(tmp_path)
    ci.tick(str(clips), str(out), api, now=1000)
    assert api.submitted == [(str(camp / "stream1.mp4"),
                              {"target_clips": 5, "clip_min_seconds": 20, "clip_max_seconds": 45,
                               "captions": False, "auto_hook": True})]
    job = ci._load_state(str(clips))["active"]["job"]
    assert job in ci.campaign_job_ids(str(clips))

    ci.tick(str(clips), str(out), api, now=1010)  # still processing
    assert "Zpracovavam" in (camp / "stav.txt").read_text()

    api.finish(job, t=1100)
    ci.tick(str(clips), str(out), api, now=1120)  # finished but not settled
    assert (camp / "stream1.mp4").exists()
    ci.tick(str(clips), str(out), api, now=1200)
    done = camp / "hotovo" / f"Stream [{job[:8]}]"
    assert sorted(os.listdir(done)) == ["clip_1.mp4", "clip_1.txt", "clip_2.mp4", "clip_2.txt"]
    txt = (done / "clip_1.txt").read_text()
    assert "YouTube title: T1" in txt and "Hashtagy: #irl #fyp" in txt and "Kredit: @marlon" in txt
    assert not (camp / "stream1.mp4").exists()
    assert "Hotovo" in (camp / "stav.txt").read_text()
    assert ci._load_state(str(clips))["active"] is None
    # The dashboard exporter leaves campaign jobs alone.
    skip = ci.campaign_job_ids(str(clips))
    assert clip_export.export_all(str(out), str(clips), now=1300, skip=skip) == []


def test_links_are_marked_done(tmp_path):
    url = "https://www.youtube.com/watch?v=abc"
    clips, camp, out, api = _setup(tmp_path, video=False, links=[url])
    ci.tick(str(clips), str(out), api, now=1000)
    job = ci._load_state(str(clips))["active"]["job"]
    api.finish(job, t=1000)
    ci.tick(str(clips), str(out), api, now=1100)
    assert (camp / "odkazy.txt").read_text().strip() == f"# hotovo {url}"
    ci.tick(str(clips), str(out), api, now=1200)
    assert len(api.submitted) == 1


def test_missing_instructions_writes_template_and_waits(tmp_path):
    clips, camp, out, api = _setup(tmp_path, instructions=None)
    ci.tick(str(clips), str(out), api, now=1000)
    assert "mam_prava: ne" in (camp / "instrukce.txt").read_text()
    ci.tick(str(clips), str(out), api, now=1010)
    assert api.submitted == []
    assert "mam_prava" in (camp / "stav.txt").read_text()


def test_failed_job_keeps_file_and_moves_on(tmp_path):
    clips, camp, out, api = _setup(tmp_path)
    ci.tick(str(clips), str(out), api, now=1000)
    job = ci._load_state(str(clips))["active"]["job"]
    api.statuses[job] = {"status": "failed", "logs": ["Download failed"]}
    ci.tick(str(clips), str(out), api, now=1010)
    assert (camp / "stream1.mp4").exists()
    assert "Download failed" in (camp / "stav.txt").read_text()
    ci.tick(str(clips), str(out), api, now=1020)
    assert len(api.submitted) == 1  # not retried until renamed


def test_submit_error_marks_link(tmp_path):
    url = "https://www.youtube.com/watch?v=bad"
    clips, camp, out, api = _setup(tmp_path, video=False, links=[url])
    api.fail_submit = "This URL can't be processed"
    ci.tick(str(clips), str(out), api, now=1000)
    assert (camp / "odkazy.txt").read_text().strip() == f"# chyba {url}"
    assert "can't be processed" in (camp / "stav.txt").read_text()


def test_file_still_copying_is_not_picked(tmp_path):
    clips, camp, out, api = _setup(tmp_path)
    os.utime(camp / "stream1.mp4", (995, 995))
    ci.tick(str(clips), str(out), api, now=1000)
    assert api.submitted == []


def test_per_video_export_folders_are_not_campaigns(tmp_path):
    clips = tmp_path / "clips"
    exported = clips / "Talk [abcdef12]"
    exported.mkdir(parents=True)
    (exported / "clip_1.mp4").write_bytes(b"x")
    os.utime(exported / "clip_1.mp4", (1, 1))
    out = tmp_path / "output"
    out.mkdir()
    api = FakeApi(str(out))
    ci.tick(str(clips), str(out), api, now=1000)
    assert api.submitted == [] and not (exported / "instrukce.txt").exists()
