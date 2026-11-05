"""Vérifications des fournisseurs vocaux, sans requête facturée."""

import wave

import pytest

from pipelineia.speech import synthesize


def test_demo_is_explicit_silent_wav(tmp_path):
    path = synthesize("Essai de narration.", tmp_path / "voice.wav", {"speech": {"provider": "demo"}})
    with wave.open(str(path)) as audio:
        assert audio.getnframes() / audio.getframerate() == 58
        assert set(audio.readframes(audio.getnframes())) == {0}


def test_espeak_fails_clearly_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("pipelineia.speech.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="espeak-ng"):
        synthesize("Une narration.", tmp_path / "voice.wav", {"speech": {"provider": "espeak"}})


def test_google_requires_voice_name(tmp_path):
    with pytest.raises(ValueError, match="google_voice"):
        synthesize("Une narration.", tmp_path / "voice.wav", {"speech": {"provider": "google"}})


def test_google_writes_provider_audio(tmp_path, monkeypatch):
    monkeypatch.setattr("pipelineia.speech._google", lambda text, config: b"valid-wav-fixture" * 8)
    path = synthesize("Une narration.", tmp_path / "voice.wav",
                      {"speech": {"provider": "google", "google_voice": "fixture"}})
    assert path.read_bytes() == b"valid-wav-fixture" * 8


def test_empty_narration_fails(tmp_path):
    with pytest.raises(ValueError, match="vide"):
        synthesize("  ", tmp_path / "voice.wav", {})


def test_system_provider_uses_local_voice(tmp_path, monkeypatch):
    calls = []
    def local_voice(text, path, config):
        calls.append(text)
        path.write_bytes(b"system-wav-fixture" * 8)
    monkeypatch.setattr("pipelineia.speech._system", local_voice)
    path = synthesize("Narration française.", tmp_path / "voice.wav", {"speech": {"provider": "system"}})
    assert calls == ["Narration française."]
    assert path.is_file()
