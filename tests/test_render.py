"""Vérifications de durée réelle et de garde-fous du montage."""

import subprocess
import wave

import pytest

from pipelineia.render import audio_duration, build_timeline, render_episode
from pipelineia.speech import ffmpeg_binary, synthesize


SCRIPT = {
    "title": "Une actualité IA vérifiée", "hook": "Que change cette annonce ?",
    "scenes": [{"narration": "Voici une annonce récente et sa conséquence concrète.",
                "on_screen": "Ce qui change", "source_ids": ["s1"]},
               {"narration": "La source officielle précise les limites de cette nouveauté.",
                "on_screen": "Les limites", "source_ids": ["s1"]}],
    "sources": [{"id": "s1", "title": "Source officielle", "url": "https://example.com/announcement"}],
}


def test_timeline_covers_episode_without_gaps():
    cues = build_timeline(SCRIPT, 58, 60)
    assert cues[0]["start"] == 0
    assert cues[-1]["end"] == 60
    for previous, following in zip(cues, cues[1:]):
        assert previous["end"] == following["start"]
    assert " ".join(cue["caption"] for cue in cues) == " ".join(s["narration"] for s in SCRIPT["scenes"])


def test_renderer_rejects_excessively_short_audio(tmp_path):
    audio = synthesize("Essai.", tmp_path / "audio.wav",
                       {"speech": {"provider": "demo"}, "video": {"duration_seconds": 4}})
    with pytest.raises(ValueError, match="accélération excessive"):
        render_episode(SCRIPT, audio, tmp_path / "render", {})


def test_actual_render_has_sixty_seconds_and_decodes(tmp_path):
    config = {"speech": {"provider": "demo"},
              "video": {"fps": 5, "preset": "ultrafast", "formats": {
                  "vertical": {"width": 270, "height": 480}}}}
    audio = synthesize("Démonstration.", tmp_path / "audio.wav", config)
    outputs = render_episode(SCRIPT, audio, tmp_path / "render", config)
    video = outputs["vertical"]
    assert video.stat().st_size > 1000
    assert abs(audio_duration(video) - 60) < .1
    # Décodage complet : détecte aussi les conteneurs et flux corrompus.
    result = subprocess.run([ffmpeg_binary(), "-v", "error", "-i", str(video), "-f", "null", "-"],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert (video.parent / "captions.srt").read_text(encoding="utf-8").endswith("nouveauté.\n")
    assert (video.parent / "vertical-cover.png").is_file()


def test_voiced_demo_has_visible_demo_label(tmp_path, monkeypatch):
    from PIL import ImageDraw
    from pipelineia.render import _card
    labels = []
    original = ImageDraw.ImageDraw.multiline_text
    def record(self, xy, text, *args, **kwargs):
        labels.append(text)
        return original(self, xy, text, *args, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "multiline_text", record)
    script = dict(SCRIPT, demo=True)
    _card(tmp_path / "demo.png", 1080, 1920, script, script["scenes"][0],
          "Une démonstration avec une voix locale.", 0, 2, False)
    assert any("PAS UNE ACTUALITÉ" in label for label in labels)
    assert not any("VOIX SILENCIEUSE" in label for label in labels)
