"""Diagnostic sans génération et traitement isolé des reprises quotidiennes."""

import copy
import logging
from datetime import datetime as RealDatetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from pipelineia import __main__ as cli


@pytest.fixture(autouse=True)
def close_added_log_handlers():
    """Évite que les invocations CLI de test conservent des fichiers ouverts."""
    root = logging.getLogger()
    previous = set(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in previous:
            root.removeHandler(handler)
            handler.close()


@pytest.fixture
def config(tmp_path):
    return {"timezone": "UTC", "paths": {"logs": str(tmp_path / "logs"),
            "state_db": str(tmp_path / "data/state.sqlite3"), "output": str(tmp_path / "output")},
            "llm": {"provider": "gemini", "model": "configured-model"},
            "speech": {"provider": "espeak"}, "publishing": {"platforms": []}}


def test_doctor_calls_only_local_ffmpeg_check_and_never_generates(config, monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "top-secret-api-key")
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg-local")
    process = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(cli.subprocess, "run", process)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/local/espeak-ng")
    generation = Mock(side_effect=AssertionError("doctor ne doit pas générer"))
    monkeypatch.setattr(cli, "run_episode", generation)
    with caplog.at_level(logging.INFO):
        assert cli.doctor(config) == 0
    process.assert_called_once_with(["ffmpeg-local", "-version"], capture_output=True, timeout=20)
    generation.assert_not_called()
    assert "top-secret-api-key" not in caplog.text
    assert "cle_gemini_presente" in caplog.text


@pytest.mark.parametrize("has_voice", [True, False])
def test_doctor_elevenlabs_never_generates_or_exposes_credentials(config, monkeypatch, caplog, has_voice):
    config["speech"] = {"provider": "elevenlabs", "elevenlabs": {"model_id": "configured-model"}}
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-private")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-private")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    if has_voice:
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "selected-voice")
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))
    monkeypatch.setattr("pipelineia.elevenlabs.requests.post", Mock(side_effect=AssertionError("Aucun appel facturable")))
    with caplog.at_level(logging.INFO):
        assert cli.doctor(config) == (0 if has_voice else 2)
    assert "gemini-private" not in caplog.text and "eleven-private" not in caplog.text


def test_doctor_cli_oauth_checks_presence_without_reading_credentials(config, tmp_path, monkeypatch, caplog):
    config["llm"]["provider"] = "gemini_cli"
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path))
    credentials = tmp_path / ".gemini/oauth_creds.json"
    credentials.parent.mkdir()
    credentials.write_text("secret-content-not-json-do-not-read", encoding="utf-8")
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg")
    process = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(cli.subprocess, "run", process)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/local/tool")
    with caplog.at_level(logging.INFO):
        assert cli.doctor(config) == 0
    assert "secret-content-not-json-do-not-read" not in caplog.text
    assert process.call_count == 1


def test_missing_api_secret_fails_diagnostic_without_api_call(config, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/local/tool")
    assert cli.doctor(config) == 2


def test_diagnostic_fails_for_missing_enabled_publication_secrets(config, monkeypatch):
    config["publishing"]["platforms"] = ["youtube"]
    monkeypatch.setenv("GEMINI_API_KEY", "fake-present-key")
    for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/local/tool")
    assert cli.doctor(config) == 2


def test_tiktok_export_only_is_not_a_missing_publishing_secret(config, monkeypatch):
    config["publishing"]["platforms"] = ["tiktok"]
    monkeypatch.setenv("GEMINI_API_KEY", "fake-present-key")
    monkeypatch.setattr(cli, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: Mock(returncode=0))
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/local/tool")
    assert cli.doctor(config) == 0


def test_main_doctor_never_runs_pipeline(config, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    diagnostic = Mock(return_value=2)
    generation = Mock()
    monkeypatch.setattr(cli, "doctor", diagnostic)
    monkeypatch.setattr(cli, "run_episode", generation)
    assert cli.main(["doctor"]) == 2
    diagnostic.assert_called_once_with(config)
    generation.assert_not_called()


def test_cli_continues_today_after_backlog_error_without_logging_secret(config, monkeypatch, caplog):
    class FrozenDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 5, 12, 0, tzinfo=tz)

    monkeypatch.setattr(cli, "datetime", FrozenDatetime)
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "State", lambda path: Mock(unfinished=lambda: ["2026-11-04-actu-ia"]))
    generation = Mock(side_effect=[RuntimeError("?access_token=secret-not-for-logs"), {"status": "complete"}])
    monkeypatch.setattr(cli, "run_episode", generation)
    with caplog.at_level(logging.INFO):
        assert cli.main(["run", "--publish"]) == 2
    assert [call.kwargs["episode_id"] for call in generation.call_args_list] == ["2026-11-04-actu-ia", "2026-11-05-actu-ia"]
    assert "secret-not-for-logs" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_explicit_episode_runs_only_that_episode(config, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    generation = Mock(return_value={"status": "publication_incomplete"})
    monkeypatch.setattr(cli, "run_episode", generation)
    assert cli.main(["run", "--publish", "--episode-id", "2026-11-03-actu-ia"]) == 2
    generation.assert_called_once_with(config, publish=True, episode_id="2026-11-03-actu-ia")


def test_unexpected_setup_error_logs_no_exception_body(config, monkeypatch, caplog):
    def fail(path):
        raise RuntimeError("secret-body-and-private-url")
    monkeypatch.setattr(cli, "load_config", fail)
    with caplog.at_level(logging.ERROR):
        assert cli.main(["doctor"]) == 1
    assert "secret-body-and-private-url" not in caplog.text
