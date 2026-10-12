import json
import os

from fastapi.testclient import TestClient

import app
import focus_check


def _gen(answer):
    return lambda frames, prompt: json.dumps(answer)


def test_check_clip_reports_the_models_verdict():
    seen = {}

    def gen(frames, prompt):
        seen["prompt"], seen["n"] = prompt, len(frames)
        return json.dumps({"match": False, "confidence": 140, "seen": "a man   eating cake"})
    r = focus_check.check_clip("c.mp4", "Kizik shoes", sampler=lambda p, n, w: [b"j"] * n, generate=gen)
    assert r == {"match": False, "confidence": 100, "seen": "a man eating cake"}
    assert "Kizik shoes" in seen["prompt"] and seen["n"] == focus_check.FRAMES


def test_check_clip_never_raises():
    def boom(frames, prompt):
        raise RuntimeError("quota")
    r = focus_check.check_clip("c.mp4", "x", sampler=lambda p, n, w: [b"j"], generate=boom)
    assert r["match"] is None and "quota" in r["seen"]
    assert focus_check.check_clip("c.mp4", "x", sampler=lambda p, n, w: [])["match"] is None
    assert focus_check.check_clip("c.mp4", "", sampler=lambda p, n, w: [b"j"])["match"] is None
    r = focus_check.check_clip("c.mp4", "x", sampler=lambda p, n, w: [b"j"],
                               generate=_gen({"match": "maybe"}))
    assert r["match"] is None


def test_check_job_checks_the_latest_version_of_each_clip(tmp_path):
    for name, t in (("V_clip_1.mp4", 1), ("subtitled_9_V_clip_1.mp4", 5), ("V_clip_2.mp4", 1),
                    ("temp_V_clip_3.mp4", 9)):
        (tmp_path / name).write_bytes(b"x")
        os.utime(tmp_path / name, (t, t))
    checked = []
    out = focus_check.check_job(str(tmp_path), "f",
                                sampler=lambda p, n, w: checked.append(os.path.basename(p)) or [b"j"],
                                generate=_gen({"match": True, "confidence": 80, "seen": "shoes"}))
    assert checked == ["subtitled_9_V_clip_1.mp4", "V_clip_2.mp4"]
    assert [c["clip"] for c in out] == [1, 2] and out[0]["match"] is True


JOB = "12345678-1234-1234-1234-123456789abc"


def test_endpoint_validates_and_checks(monkeypatch):
    client = TestClient(app.app)
    assert client.post("/api/focus-check", json={"job_id": "../x", "focus": "f"}).status_code == 400
    monkeypatch.setitem(app.jobs, JOB, {"status": "processing", "logs": []})
    assert client.post("/api/focus-check", json={"job_id": JOB, "focus": "f"}).status_code == 409

    app.jobs[JOB]["status"] = "completed"
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls = []
    monkeypatch.setattr(focus_check, "check_job",
                        lambda d, f, **kw: calls.append((d, f, kw)) or [{"clip": 1, "match": False}])
    r = client.post("/api/focus-check", json={"job_id": JOB, "focus": "Kizik"})
    assert r.status_code == 200 and r.json()["clips"] == [{"clip": 1, "match": False}]
    assert calls[0][0].endswith(JOB) and calls[0][1] == "Kizik" and calls[0][2]["api_key"] == "k"
