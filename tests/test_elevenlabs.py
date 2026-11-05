"""Contrats ElevenLabs et cache des générations payantes, avec API simulée."""
import base64
import hashlib
import json
import subprocess
import wave
from unittest.mock import Mock

import pytest
import requests

from pipelineia import elevenlabs as eleven


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "private-api-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice123")
    return {"speech": {"provider": "elevenlabs", "elevenlabs": {
        "model_id": "eleven_flash_v2_5", "language_code": "fr", "output_format": "mp3_44100_128",
        "voice_settings": {"stability": .5, "similarity_boost": .75, "style": 0,
                           "use_speaker_boost": True, "speed": 1.0}}}}


def fixture_alignment(text):
    return {"characters": list(text), "character_start_times_seconds": [i * .1 for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) * .1 for i in range(len(text))]}


def api_response(text="Bonjour.", code=200, alignment=True, audio=b"mp3-audio-fixture" * 10):
    body = {"audio_base64": base64.b64encode(audio).decode(),
            "alignment": fixture_alignment(text) if alignment else None}
    return Mock(status_code=code, json=Mock(return_value=body))


def write_wav(path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        wav.writeframes(b"\0\0" * 44100)


@pytest.fixture
def conversion(monkeypatch):
    converter = Mock(side_effect=lambda source, output: write_wav(output))
    monkeypatch.setattr(eleven, "_convert", converter)
    return converter


def test_official_endpoint_payload_and_alignment(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    kwargs = post.call_args.kwargs
    assert post.call_args.args == ("https://api.elevenlabs.io/v1/text-to-speech/voice123/with-timestamps",)
    assert kwargs["headers"]["xi-api-key"] == "private-api-key"
    assert kwargs["params"] == {"output_format": "mp3_44100_128"}
    assert kwargs["json"]["language_code"] == "fr"
    assert kwargs["json"]["voice_settings"]["speed"] == 1.0
    assert kwargs["allow_redirects"] is False
    alignment = json.loads(output.with_suffix(".alignment.json").read_text(encoding="utf-8"))
    assert alignment["text"] == "Bonjour."
    assert alignment["audio_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "private-api-key" not in output.with_suffix(".elevenlabs.json").read_text()


def test_same_audio_reuses_cache_without_api_or_conversion(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == conversion.call_count == 1


def test_deleted_or_corrupted_wav_recovers_from_paid_mp3(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    output.write_bytes(b"broken")
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    output.unlink()
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 1 and conversion.call_count == 3
    assert eleven._valid_wav(output)


def test_missing_mp3_keeps_verified_wav_without_api(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    output.with_suffix(".elevenlabs.mp3").unlink()
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == conversion.call_count == 1


def test_corrupt_paid_cache_does_not_silently_pay_again(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    output.write_bytes(b"broken")
    output.with_suffix(".elevenlabs.mp3").write_bytes(b"broken")
    with pytest.raises(eleven.ElevenLabsError, match="corrompu"):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 1


def test_conversion_failure_resumes_without_second_paid_call(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    conversion.side_effect = eleven.ElevenLabsError("Conversion interrompue")
    output = tmp_path / "voice.wav"
    with pytest.raises(eleven.ElevenLabsError):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    conversion.side_effect = lambda source, output: write_wav(output)
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 1


@pytest.mark.parametrize("change", ["text", "voice", "model", "speed"])
def test_changed_generation_parameters_invalidate_cache(config, conversion, tmp_path, monkeypatch, change):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    settings = config["speech"]["elevenlabs"]
    text = "Bonjour."
    if change == "text":
        text = "Bonjour encore."
    elif change == "voice":
        settings["voice_id"] = "anotherVoice"
    elif change == "model":
        settings["model_id"] = "eleven_multilingual_v2"
    else:
        settings["voice_settings"]["speed"] = 1.1
    eleven.synthesize_elevenlabs(text, output, config)
    assert post.call_count == 2


def test_api_key_rotation_does_not_invalidate_audio(config, conversion, tmp_path, monkeypatch):
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "replacement-key")
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 1


@pytest.mark.parametrize("missing", ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"])
def test_missing_credentials_fail_before_api(config, conversion, tmp_path, monkeypatch, missing):
    monkeypatch.delenv(missing)
    post = Mock()
    monkeypatch.setattr(eleven.requests, "post", post)
    with pytest.raises(eleven.ElevenLabsError, match=missing):
        eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    post.assert_not_called()


@pytest.mark.parametrize("code", [401, 403, 402, 429, 422, 500])
def test_remote_error_never_retries_or_leaks_secret(config, conversion, tmp_path, monkeypatch, code):
    response = api_response(code=code)
    response.json.return_value = {"error": "private-api-key full raw body"}
    post = Mock(return_value=response)
    monkeypatch.setattr(eleven.requests, "post", post)
    with pytest.raises(eleven.ElevenLabsError) as caught:
        eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    assert post.call_count == 1
    assert "private-api-key" not in str(caught.value)
    conversion.assert_not_called()


def test_timeout_is_persistently_ambiguous_no_blind_retry(config, conversion, tmp_path, monkeypatch):
    post = Mock(side_effect=requests.Timeout("private-api-key"))
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    with pytest.raises(eleven.ElevenLabsError, match="perdue"):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    with pytest.raises(eleven.ElevenLabsError, match="ambiguë"):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 1
    assert "private-api-key" not in output.with_suffix(".elevenlabs.json").read_text()


def test_rejected_quota_can_be_retried_later(config, conversion, tmp_path, monkeypatch):
    post = Mock(side_effect=[api_response(code=429), api_response()])
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    with pytest.raises(eleven.ElevenLabsError):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 2


@pytest.mark.parametrize("alignment", [None, {"characters": ["x"]}, fixture_alignment("Autre texte")])
def test_bad_alignment_keeps_paid_audio_for_estimated_captions(config, conversion, tmp_path, monkeypatch, alignment):
    response = api_response()
    response.json.return_value["alignment"] = alignment
    monkeypatch.setattr(eleven.requests, "post", Mock(return_value=response))
    output = eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    assert eleven._valid_wav(output)
    assert not output.with_suffix(".alignment.json").exists()


def test_normalized_alignment_only_used_if_exact_input_match(config, conversion, tmp_path, monkeypatch):
    response = api_response(alignment=False)
    response.json.return_value["normalized_alignment"] = fixture_alignment("Bonjour.")
    monkeypatch.setattr(eleven.requests, "post", Mock(return_value=response))
    output = eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    assert output.with_suffix(".alignment.json").exists()


@pytest.mark.parametrize("mutate", ["nan", "backwards", "negative", "different-length"])
def test_invalid_timing_is_not_published(config, conversion, tmp_path, monkeypatch, mutate):
    response = api_response()
    timing = response.json.return_value["alignment"]
    if mutate == "nan":
        timing["character_end_times_seconds"][0] = float("nan")
    elif mutate == "backwards":
        timing["character_start_times_seconds"][2] = .01
    elif mutate == "negative":
        timing["character_start_times_seconds"][0] = -.01
    else:
        timing["characters"].pop()
    monkeypatch.setattr(eleven.requests, "post", Mock(return_value=response))
    output = eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    assert not output.with_suffix(".alignment.json").exists()


def test_multilingual_v2_omits_unsupported_language(config, conversion, tmp_path, monkeypatch):
    config["speech"]["elevenlabs"]["model_id"] = "eleven_multilingual_v2"
    post = Mock(return_value=api_response())
    monkeypatch.setattr(eleven.requests, "post", post)
    eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    assert "language_code" not in post.call_args.kwargs["json"]


def test_malformed_base64_is_ambiguous_and_not_retried(config, conversion, tmp_path, monkeypatch):
    response = api_response()
    response.json.return_value["audio_base64"] = "not base64!!"
    post = Mock(return_value=response)
    monkeypatch.setattr(eleven.requests, "post", post)
    output = tmp_path / "voice.wav"
    with pytest.raises(eleven.ElevenLabsError, match="invalide"):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    with pytest.raises(eleven.ElevenLabsError, match="ambiguë"):
        eleven.synthesize_elevenlabs("Bonjour.", output, config)
    assert post.call_count == 1


@pytest.mark.parametrize("field,value", [("speed", 2), ("stability", -1), ("similarity_boost", float("nan")), ("use_speaker_boost", "yes")])
def test_invalid_settings_never_consume_credits(config, tmp_path, monkeypatch, field, value):
    config["speech"]["elevenlabs"]["voice_settings"][field] = value
    post = Mock()
    monkeypatch.setattr(eleven.requests, "post", post)
    with pytest.raises(eleven.ElevenLabsError):
        eleven.synthesize_elevenlabs("Bonjour.", tmp_path / "voice.wav", config)
    post.assert_not_called()


def test_actual_mp3_to_wav_conversion_without_api(tmp_path):
    from pipelineia.speech import ffmpeg_binary
    source = tmp_path / "fixture.mp3"
    subprocess.run([ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=0.25", "-c:a", "libmp3lame", str(source)],
                   check=True, capture_output=True, timeout=30)
    output = tmp_path / "voice.wav"
    eleven._convert(source, output)
    assert eleven._valid_wav(output)
