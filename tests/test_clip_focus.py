from clip_selection import focus_preamble


def test_no_focus_no_preamble():
    assert focus_preamble({}) == ""
    assert focus_preamble({"CLIP_FOCUS": "   "}) == ""


def test_focus_preamble_carries_the_brief():
    text = focus_preamble({"CLIP_FOCUS": "Kizik shoes,\n golden treadmill challenge at 34:18"})
    assert text.startswith("CAMPAIGN FOCUS")
    assert "Kizik shoes, golden treadmill challenge at 34:18" in text
    assert "under 30" in text


def test_focus_is_capped():
    assert len(focus_preamble({"CLIP_FOCUS": "x" * 5000})) < 1000


def test_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("CLIP_FOCUS", "the treadmill")
    assert "the treadmill" in focus_preamble()
    monkeypatch.delenv("CLIP_FOCUS")
    assert focus_preamble() == ""
