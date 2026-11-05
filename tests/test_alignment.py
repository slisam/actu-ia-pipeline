"""Alignement mesuré, pauses, changement de tempo et données périmées."""
import hashlib
import json
import re
import wave

import pytest

from pipelineia.alignment import aligned_timeline
from pipelineia.render import audio_duration, render_episode


@pytest.fixture
def aligned(tmp_path):
    script = {"title": "Une annonce", "hook": "Une annonce expliquée",
              "scenes": [{"narration": "un deux trois quatre cinq six sept huit neuf dix", "on_screen": "Les faits"},
                         {"narration": "onze douze treize quatorze quinze seize dixsept dixhuit dixneuf vingt", "on_screen": "Les limites"}]}
    text = " ".join(scene["narration"] for scene in script["scenes"])
    audio = tmp_path / "voice.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 8000 * 58)
    starts = [0.0] * len(text)
    for index, match in enumerate(re.finditer(r"\S+", text)):
        base = index * 2 if index < 10 else 40 + index - 10
        for position in range(match.start(), match.end()):
            starts[position] = base + (position - match.start()) * .01
        if match.end() < len(text):
            starts[match.end()] = base + .5
    data = {"provider": "elevenlabs", "text": text,
            "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
            "alignment": {"characters": list(text), "character_start_times_seconds": starts,
                          "character_end_times_seconds": [value + .008 for value in starts]}}
    sidecar = audio.with_suffix(".alignment.json")
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    return script, audio, sidecar, data


def test_nonuniform_alignment_preserves_scene_pause_and_caption_text(aligned):
    script, audio, _, _ = aligned
    cues, status = aligned_timeline(script, audio, 58, 58, 60)
    assert status == "verified"
    assert [cue["start"] for cue in cues] == [0, 18, 40, 49]
    assert [cue["scene"] for cue in cues] == [0, 0, 1, 1]
    assert " ".join(cue["caption"] for cue in cues) == " ".join(s["narration"] for s in script["scenes"])
    assert cues[-1]["end"] == 60
    assert all(first["end"] == second["start"] for first, second in zip(cues, cues[1:]))


def test_alignment_tracks_audio_tempo(aligned):
    script, audio, _, _ = aligned
    cues, status = aligned_timeline(script, audio, 72.5, 58, 60)
    assert status == "verified"
    assert cues[2]["start"] == 32


@pytest.mark.parametrize("damage,reason", [("hash", "audio_mismatch"), ("text", "text_mismatch"),
                                          ("time", "invalid_times"), ("nan", "invalid_times"),
                                          ("arrays", "invalid")])
def test_invalid_alignment_is_not_claimed_as_synchronized(aligned, damage, reason):
    script, audio, sidecar, data = aligned
    if damage == "hash":
        data["audio_sha256"] = "outdated"
    elif damage == "text":
        data["text"] = "autre narration"
    elif damage == "time":
        data["alignment"]["character_start_times_seconds"][1] = 999
    elif damage == "nan":
        data["alignment"]["character_end_times_seconds"][0] = float("nan")
    else:
        data["alignment"]["characters"].pop()
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    assert aligned_timeline(script, audio, 58, 58, 60) == (None, reason)


def test_actual_aligned_render_keeps_sixty_seconds(aligned, tmp_path):
    script, audio, _, _ = aligned
    output = tmp_path / "render"
    videos = render_episode(script, audio, output, {"video": {"fps": 5, "preset": "ultrafast",
        "formats": {"vertical": {"width": 270, "height": 480}}}})
    timing = json.loads((output / "timing.json").read_text(encoding="utf-8"))
    assert timing["method"] == "elevenlabs_character_alignment"
    assert timing["alignment_status"] == "verified"
    assert "00:00:40,000" in (output / "captions.srt").read_text(encoding="utf-8")
    assert abs(audio_duration(videos["vertical"]) - 60) < .1
