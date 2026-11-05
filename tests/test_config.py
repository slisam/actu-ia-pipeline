"""Configuration portable et validation des formats avant toute dépense."""

import copy
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError

import pytest
import yaml

from pipelineia.config import load_config


@pytest.fixture
def settings():
    return {"timezone": "Europe/Paris", "llm": {"provider": "gemini_cli"},
            "video": {"duration_seconds": 60,
                      "formats": {"vertical": {"width": 1080, "height": 1920}}}}


def write_config(tmp_path, settings):
    """Écrit un YAML réel isolé des identifiants utilisateur."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings), encoding="utf-8")
    return path


def test_default_paths_are_relative_to_config_not_current_directory(tmp_path, settings, monkeypatch):
    directory = tmp_path / "project"
    directory.mkdir()
    path = write_config(directory, settings)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = load_config(path)
    assert config["project_root"] == str(directory)
    assert Path(config["paths"]["output"]) == directory / "output"
    assert Path(config["paths"]["state_db"]) == directory / "data/state.sqlite3"
    assert Path(config["paths"]["logs"]) == directory / "logs"
    assert not (elsewhere / "output").exists()


def test_explicit_absolute_paths_remain_unchanged(tmp_path, settings):
    settings["paths"] = {key: str(tmp_path / "custom" / key) for key in ("output", "state_db", "logs")}
    config = load_config(write_config(tmp_path, settings))
    assert config["paths"] == settings["paths"]


def test_dotenv_never_overrides_process_secrets(tmp_path, settings, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "process-secret")
    (tmp_path / ".env").write_text("GEMINI_API_KEY=file-secret\n", encoding="utf-8")
    load_config(write_config(tmp_path, settings))
    import os
    assert os.environ["GEMINI_API_KEY"] == "process-secret"


@pytest.mark.parametrize("payload", [None, [], "invalid", 42])
def test_non_object_yaml_is_rejected(tmp_path, payload):
    with pytest.raises(ValueError, match="objet YAML"):
        load_config(write_config(tmp_path, payload))


@pytest.mark.parametrize("provider", ["openai", "automatic-paid-fallback", "unknown"])
def test_unsupported_provider_rejected_before_run(tmp_path, settings, provider):
    settings["llm"]["provider"] = provider
    with pytest.raises(ValueError, match="llm.provider"):
        load_config(write_config(tmp_path, settings))


@pytest.mark.parametrize("duration", [0, 30, 61, 120])
def test_duration_is_exactly_one_minute(tmp_path, settings, duration):
    settings["video"]["duration_seconds"] = duration
    with pytest.raises(ValueError, match="60 secondes"):
        load_config(write_config(tmp_path, settings))


@pytest.mark.parametrize("value", [0, 127, 129, 1081, "1080", None, True])
def test_dimensions_require_even_integer_at_least_128(tmp_path, settings, value):
    settings["video"]["formats"]["vertical"]["width"] = value
    with pytest.raises(ValueError, match="dimensions"):
        load_config(write_config(tmp_path, settings))


def test_unknown_format_rejected(tmp_path, settings):
    settings["video"]["formats"] = {"ultrawide": {"width": 1920, "height": 1080}}
    with pytest.raises(ValueError, match="Format vidéo inconnu"):
        load_config(write_config(tmp_path, settings))


def test_empty_formats_rejected(tmp_path, settings):
    settings["video"]["formats"] = {}
    with pytest.raises(ValueError, match="format vidéo"):
        load_config(write_config(tmp_path, settings))


def test_unknown_timezone_rejected(tmp_path, settings):
    settings["timezone"] = "Mars/Unknown"
    with pytest.raises(ZoneInfoNotFoundError):
        load_config(write_config(tmp_path, settings))
