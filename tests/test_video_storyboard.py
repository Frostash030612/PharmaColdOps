"""Visual-draft plans and edit bounds, not human authorship or course completion."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("video_builder", ROOT / "scripts/build_demo_videos.py")
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)


def plan():
    return json.loads(video.PLAN.read_text(encoding="utf-8"))


def test_both_visual_drafts_have_exact_five_minute_plans():
    data = plan()
    video.validate_plan(data)
    assert [sum(s["seconds"] for s in data[k]) for k in ["promotion", "system"]] == [300, 300]
    assert "no audio" in data["scope"] and "not a spoken transcript" in data["scope"]
    assert [s["slide"] for s in data["system"]] == list(range(1, 11))


@pytest.mark.parametrize("mutation,match", [
    (lambda p:p["promotion"][0].update(seconds=9), "exactly 300"),
    (lambda p:p["promotion"][1].update(id="title"), "duplicate"),
    (lambda p:p["promotion"][2].update(clip="../private.webm"), "unsafe"),
    (lambda p:p["promotion"][2].update(slide=1), "one visual source"),
    (lambda p:p["system"][0].update(slide=2), "10-slide order"),
    (lambda p:p["system"][0].update(notes=[]), "invalid scene"),
])
def test_invalid_storyboards_fail_closed(mutation, match):
    data = copy.deepcopy(plan()); mutation(data)
    with pytest.raises(ValueError, match=match):
        video.validate_plan(data)


def test_trim_preserves_only_declared_observed_source_bounds():
    assert video.clip_bounds({"tail":10}, 44.24) == pytest.approx((34.24,44.24))
    assert video.clip_bounds({"trim_end":30}, 66.24) == pytest.approx((0,36.24))
    assert video.clip_bounds({"take":50}, 98.44) == (0,50)
    with pytest.raises(ValueError, match="source trim"):
        video.clip_bounds({"trim_end":100}, 20)


def test_note_events_stay_in_scene_and_are_not_authentic_speech_transcripts():
    for kind in ("promotion", "system"):
        offset = 0
        for scene in plan()[kind]:
            events = video.note_events(scene, offset)
            assert all(offset < a < b < offset + scene["seconds"] for a,b,_ in events)
            assert all(left[1] < right[0] for left,right in zip(events, events[1:]))
            offset += scene["seconds"]
        assert offset == 300
    assert video.timestamp(3661.25) == "01:01:01,250"
    assert video.timestamp(3661.25, ass=True) == "1:01:01.25"


def test_overlay_notes_fit_two_lines_and_preserve_draft_status(tmp_path):
    scene = plan()["promotion"][7]
    video.write_notes(tmp_path, video.note_events(scene), tmp_path)
    ass = (tmp_path / "notes.ass").read_text()
    assert "Scripted demo review only" in ass and "PlayResY: 1080" in ass
    assert all(line.count("\\N") <= 1 for line in ass.splitlines() if line.startswith("Dialogue:"))


def test_source_deck_notes_and_visible_parts_cannot_be_changed(tmp_path):
    from zipfile import ZipFile
    source = ROOT / plan()["source_deck"]
    copy_path = tmp_path / "changed.pptx"
    with ZipFile(source) as original, ZipFile(copy_path,"w") as changed:
        for name in original.namelist():
            data = original.read(name)
            if name == "ppt/slides/slide1.xml":
                data = data.replace(b"PharmaColdOps", b"Changed evidence", 1)
            changed.writestr(name,data)
    with pytest.raises(ValueError, match="visible source slide changed"):
        video.visible_deck_unchanged(source,copy_path)
