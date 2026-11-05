"""Vérifie le parcours quotidien et sa reprise sans service payant ni rendu réel."""

from __future__ import annotations

import copy
import json
from datetime import datetime as RealDatetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from pipelineia import run
from pipelineia.state import State


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """Isole les fichiers, l'horloge et toutes les frontières externes."""
    clock = [RealDatetime(2026, 11, 5, 10, 0, 0)]

    class FrozenDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            value = clock[0]
            return value.replace(tzinfo=tz) if tz else value

    monkeypatch.setattr(run, "datetime", FrozenDatetime)
    config = {
        "timezone": "UTC", "paths": {"state_db": str(tmp_path / "data/state.sqlite3"),
        "output": str(tmp_path / "output")}, "video": {"duration_seconds": 60, "fps": 30,
        "formats": {"vertical": {"width": 1080, "height": 1920}}},
        "speech": {"provider": "espeak", "voice": "fr-fr", "rate": 155},
        "publishing": {"platforms": ["youtube"]},
    }
    articles = [{"id": "a1", "title": "Une annonce", "url": "https://example.org/announcement"}]
    script = {"title": "Une annonce expliquée", "hook": "Voici une annonce à bien comprendre.",
              "scenes": [{"narration": "Voici une annonce à bien comprendre.",
                          "on_screen": "Une annonce", "source_ids": ["a1"]}],
              "sources": copy.deepcopy(articles)}
    collect = Mock(return_value=articles)
    writer = Mock(return_value=script)

    def voice(text, output, settings):
        output.write_bytes(b"wav")
        return output

    def render(script, audio, output, settings):
        videos = {}
        for name in settings["video"]["formats"]:
            path = output / f"{name}.mp4"
            path.write_bytes(b"valid-video-content")
            videos[name] = path
        return videos

    speech = Mock(side_effect=voice)
    renderer = Mock(side_effect=render)
    publisher = Mock(return_value={"youtube": {"status": "succeeded", "remote_id": "yt1"}})
    for name, value in {"collect_news": collect, "write_script": writer, "synthesize": speech,
                        "render_episode": renderer, "publish_episode": publisher}.items():
        monkeypatch.setattr(run, name, value)
    return {"config": config, "clock": clock, "script": script, "collect": collect,
            "writer": writer, "speech": speech, "renderer": renderer, "publisher": publisher}


def test_no_news_stops_before_generation_voice_render_or_publish(pipeline):
    pipeline["collect"].return_value = []
    result = run.run_episode(pipeline["config"], publish=True)
    assert result["status"] == "no_news"
    for stage in ("writer", "speech", "renderer", "publisher"):
        pipeline[stage].assert_not_called()
    assert State(pipeline["config"]["paths"]["state_db"]).get(result["episode_id"]) is None


def test_same_day_reuses_script_and_verified_mp4(pipeline):
    config_before = copy.deepcopy(pipeline["config"])
    first = run.run_episode(pipeline["config"], publish=True)
    second = run.run_episode(pipeline["config"], publish=True)
    assert first["episode_id"] == second["episode_id"] == "2026-11-05-actu-ia"
    assert first["manifest"]["hashes"] == second["manifest"]["hashes"]
    for stage in ("collect", "writer", "speech", "renderer"):
        pipeline[stage].assert_called_once()
    # La reprise de publication passe toujours par son journal idempotent.
    assert pipeline["publisher"].call_count == 2
    assert pipeline["config"] == config_before


def test_corrupted_mp4_is_rendered_again_using_cached_script(pipeline):
    first = run.run_episode(pipeline["config"])
    Path(first["manifest"]["videos"]["vertical"]).write_bytes(b"interrupted-transfer")
    second = run.run_episode(pipeline["config"])
    assert second["status"] == "complete"
    assert pipeline["collect"].call_count == pipeline["writer"].call_count == 1
    assert pipeline["speech"].call_count == pipeline["renderer"].call_count == 2
    assert Path(second["manifest"]["videos"]["vertical"]).read_bytes() == b"valid-video-content"


def test_missing_mp4_is_rendered_again(pipeline):
    first = run.run_episode(pipeline["config"])
    Path(first["manifest"]["videos"]["vertical"]).unlink()
    assert run.run_episode(pipeline["config"])["status"] == "complete"
    assert pipeline["renderer"].call_count == 2
    pipeline["writer"].assert_called_once()


def test_voice_parameter_change_invalidates_render_cache(pipeline):
    run.run_episode(pipeline["config"])
    pipeline["config"]["speech"]["rate"] = 160
    assert run.run_episode(pipeline["config"])["status"] == "complete"
    assert pipeline["renderer"].call_count == 2
    pipeline["writer"].assert_called_once()


def test_failed_render_preserves_script_and_redacts_error_in_state(pipeline):
    original_renderer = pipeline["renderer"].side_effect
    pipeline["renderer"].side_effect = RuntimeError("signed-upload?access_token=hidden-secret")
    with pytest.raises(RuntimeError):
        run.run_episode(pipeline["config"])
    state = State(pipeline["config"]["paths"]["state_db"])
    row = state.get("2026-11-05-actu-ia")
    assert row["status"] == "failed"
    assert row["error"] == "RuntimeError"
    assert "hidden-secret" not in row["error"]
    assert json.loads(row["script_json"])["title"] == pipeline["script"]["title"]
    pipeline["renderer"].side_effect = original_renderer
    assert run.run_episode(pipeline["config"])["status"] == "complete"
    pipeline["writer"].assert_called_once()
    pipeline["collect"].assert_called_once()


def test_next_day_collection_excludes_previous_sources(pipeline):
    run.run_episode(pipeline["config"])
    pipeline["clock"][0] += timedelta(days=1)
    pipeline["collect"].return_value = []
    second = run.run_episode(pipeline["config"])
    assert second["episode_id"] == "2026-11-06-actu-ia"
    assert second["status"] == "no_news"
    assert pipeline["collect"].call_args.kwargs["used_urls"] == {"https://example.org/announcement"}
    pipeline["writer"].assert_called_once()


def test_demo_cannot_publish_and_never_contacts_sources(pipeline):
    with pytest.raises(ValueError, match="démonstration"):
        run.run_episode(pipeline["config"], demo=True, publish=True)
    for stage in ("collect", "writer", "speech", "renderer", "publisher"):
        pipeline[stage].assert_not_called()
    result = run.run_episode(pipeline["config"], demo=True, quick=True, silent=True)
    assert result["manifest"]["demo"] is True
    pipeline["collect"].assert_not_called()
    pipeline["writer"].assert_not_called()
    pipeline["publisher"].assert_not_called()
    assert pipeline["speech"].call_args.args[2]["speech"]["provider"] == "demo"
    assert pipeline["config"]["speech"]["provider"] == "espeak"


def test_silent_real_episode_rejected_before_any_work(pipeline):
    with pytest.raises(ValueError, match="silencieuse"):
        run.run_episode(pipeline["config"], silent=True)
    pipeline["collect"].assert_not_called()


def test_publication_manifest_contains_only_existing_hashed_files(pipeline):
    result = run.run_episode(pipeline["config"], publish=True)
    manifest = json.loads((Path(result["directory"]) / "manifest.json").read_text(encoding="utf-8"))
    for name, value in manifest["videos"].items():
        assert Path(value).is_file()
        assert manifest["hashes"][name] == run.sha256(Path(value))
    assert manifest["demo"] is False
    assert "https://example.org/announcement" in manifest["description"]


@pytest.mark.parametrize("status", ["pending", "failed", "uncertain", "conflict", "not_configured"])
def test_partial_publication_remains_incomplete_and_resumes_cached_files(pipeline, status):
    pipeline["publisher"].return_value = {"youtube": {"status": "succeeded"},
                                          "instagram": {"status": status}}
    first = run.run_episode(pipeline["config"], publish=True)
    assert first["status"] == "publication_incomplete"
    state = State(pipeline["config"]["paths"]["state_db"])
    assert state.get(first["episode_id"])["status"] == "publication_incomplete"
    assert state.unfinished() == [first["episode_id"]]
    assert "https://example.org/announcement" in state.used_urls()
    pipeline["clock"][0] += timedelta(days=1)
    pipeline["publisher"].return_value = {"youtube": {"status": "succeeded"},
                                          "instagram": {"status": "succeeded"}}
    second = run.run_episode(pipeline["config"], publish=True, episode_id=first["episode_id"])
    assert second["episode_id"] == first["episode_id"]
    assert second["status"] == "complete"
    assert state.unfinished() == []
    for stage in ("collect", "writer", "speech", "renderer"):
        pipeline[stage].assert_called_once()


def test_tiktok_export_only_is_an_explicit_terminal_destination(pipeline):
    pipeline["publisher"].return_value = {"youtube": {"status": "succeeded"},
                                          "tiktok": {"status": "export_only"}}
    result = run.run_episode(pipeline["config"], publish=True)
    assert result["status"] == "complete"
    assert result["manifest"]["publication"]["tiktok"]["status"] == "export_only"


def test_corrupt_manifest_is_rebuilt_without_model_regeneration(pipeline):
    first = run.run_episode(pipeline["config"])
    (Path(first["directory"]) / "manifest.json").write_text('{"partial":', encoding="utf-8")
    assert run.run_episode(pipeline["config"])["status"] == "complete"
    pipeline["writer"].assert_called_once()
    assert pipeline["renderer"].call_count == 2


def test_real_episode_cannot_publish_quick_resolution(pipeline):
    with pytest.raises(ValueError, match="résolution"):
        run.run_episode(pipeline["config"], quick=True, publish=True)
    pipeline["collect"].assert_not_called()


def test_empty_publication_destinations_are_not_reported_complete(pipeline):
    pipeline["config"]["publishing"]["platforms"] = []
    with pytest.raises(ValueError, match="destination"):
        run.run_episode(pipeline["config"], publish=True)
    pipeline["collect"].assert_not_called()


@pytest.mark.parametrize("episode_id", ["../../escape", "demo", "2026-11-05", "other"])
def test_explicit_episode_identifier_cannot_escape_output(pipeline, episode_id):
    with pytest.raises(ValueError, match="Identifiant"):
        run.run_episode(pipeline["config"], episode_id=episode_id)
    pipeline["collect"].assert_not_called()


def test_cache_missing_one_expected_format_rebuilds_all_formats(pipeline):
    pipeline["config"]["video"]["formats"]["square"] = {"width": 1080, "height": 1080}
    first = run.run_episode(pipeline["config"])
    path = Path(first["directory"]) / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["videos"]["square"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    second = run.run_episode(pipeline["config"])
    assert set(second["manifest"]["videos"]) == {"vertical", "square"}
    assert pipeline["renderer"].call_count == 2
    pipeline["writer"].assert_called_once()


def test_published_results_are_persisted_inside_manifest(pipeline):
    result = run.run_episode(pipeline["config"], publish=True)
    manifest = json.loads((Path(result["directory"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["publication"] == pipeline["publisher"].return_value


def test_stale_source_expires_before_speech_render_and_publication(pipeline):
    pipeline["script"]["sources"][0]["published_at"] = "2026-11-01T08:00:00+00:00"
    result = run.run_episode(pipeline["config"], publish=True)
    assert result["status"] == "expired"
    assert State(pipeline["config"]["paths"]["state_db"]).get(result["episode_id"])["status"] == "expired"
    for stage in ("speech", "renderer", "publisher"):
        pipeline[stage].assert_not_called()


def test_cached_old_episode_without_source_date_also_expires(pipeline):
    result = run.run_episode(pipeline["config"])
    pipeline["clock"][0] += timedelta(days=3)
    expired = run.run_episode(pipeline["config"], publish=True, episode_id=result["episode_id"])
    assert expired["status"] == "expired"
    pipeline["publisher"].assert_not_called()
    pipeline["writer"].assert_called_once()
    assert State(pipeline["config"]["paths"]["state_db"]).unfinished() == []


def test_configured_freshness_window_controls_source_expiry(pipeline):
    pipeline["config"]["news"] = {"max_age_hours": 12}
    pipeline["script"]["sources"][0]["published_at"] = "2026-11-04T20:00:00+00:00"
    assert run.run_episode(pipeline["config"], publish=True)["status"] == "expired"
    pipeline["publisher"].assert_not_called()


@pytest.mark.parametrize("broken_manifest", [[], None, "partial"])
def test_manifest_with_wrong_json_shape_is_rebuilt(pipeline, broken_manifest):
    result = run.run_episode(pipeline["config"])
    manifest = Path(result["directory"]) / "manifest.json"
    manifest.write_text(json.dumps(broken_manifest), encoding="utf-8")
    assert run.run_episode(pipeline["config"])["status"] == "complete"
    assert pipeline["renderer"].call_count == 2
    pipeline["writer"].assert_called_once()
