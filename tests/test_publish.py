"""Contrats API et reprise des publications, sans compte ni appel réseau."""

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from pipelineia import publish


def response(code=200, payload=None, headers=None):
    """Construit une réponse HTTP minimale pour le contrat testé."""
    result = Mock(status_code=code, headers=headers or {})
    result.json.return_value = {} if payload is None else payload
    return result


@pytest.fixture
def episode(tmp_path):
    """Épisode portable contenant un faux MP4 de dix octets."""
    (tmp_path / "vertical.mp4").write_bytes(b"0123456789")
    manifest = {"episode_id": "2026-11-05-test", "title": "Actualité IA", "description": "Sources vérifiées",
                "videos": {"vertical": "vertical.mp4"}, "demo": False}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


@pytest.fixture
def youtube_config(tmp_path, monkeypatch):
    """Active les secrets fictifs et isole SQLite."""
    for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "test-secret")
    return {"paths": {"state_db": str(tmp_path / "state.sqlite3")},
            "publishing": {"platforms": ["youtube"], "youtube": {"privacy": "private"}}}


def test_readiness_names_missing_secrets(monkeypatch):
    for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    ready = publish.publishing_readiness({"publishing": {"platforms": ["youtube", "tiktok"]}})
    assert ready["youtube"]["missing"] == ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    assert ready["tiktok"]["status"] == "export_only"


def test_demo_never_calls_network(episode, youtube_config, monkeypatch):
    path = episode / "manifest.json"
    data = json.loads(path.read_text())
    data["demo"] = True
    path.write_text(json.dumps(data))
    network = Mock()
    monkeypatch.setattr(publish, "_youtube_session", network)
    with pytest.raises(publish.PublishError, match="démonstration"):
        publish.publish_episode(episode, youtube_config)
    network.assert_not_called()


def test_youtube_upload_and_idempotent_rerun(episode, youtube_config, monkeypatch):
    session = Mock()
    url = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret"
    session.post.return_value = response(headers={"Location": url})
    session.put.return_value = response(201, {"id": "abc123"})
    monkeypatch.setattr(publish, "_youtube_session", lambda: session)
    first = publish.publish_episode(episode, youtube_config)
    second = publish.publish_episode(episode, youtube_config)
    assert first["youtube"]["status"] == second["youtube"]["status"] == "succeeded"
    session.post.assert_called_once()
    session.put.assert_called_once()
    kwargs = session.post.call_args.kwargs
    assert kwargs["params"]["uploadType"] == "resumable"
    assert kwargs["json"]["status"]["privacyStatus"] == "private"
    assert kwargs["json"]["status"]["containsSyntheticMedia"] is True
    assert "upload_id" not in (episode / "publication.json").read_text()


def test_youtube_lost_final_response_recovers_same_session(episode, youtube_config, monkeypatch):
    session = Mock()
    session.post.return_value = response(headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=secret"})
    session.put.side_effect = [requests.Timeout("token=very-secret"), response(200, {"id": "found-after-timeout"})]
    monkeypatch.setattr(publish, "_youtube_session", lambda: session)
    first = publish.publish_episode(episode, youtube_config)
    assert first["youtube"]["status"] == "uncertain"
    assert "very-secret" not in json.dumps(first)
    second = publish.publish_episode(episode, youtube_config)
    assert second["youtube"]["remote_id"] == "found-after-timeout"
    assert second["youtube"]["status"] == "succeeded"
    session.post.assert_called_once()
    assert session.put.call_args.kwargs["headers"]["Content-Range"] == "bytes */10"


def test_youtube_partial_upload_resumes_remaining_bytes(episode, youtube_config, monkeypatch):
    session = Mock()
    session.post.return_value = response(headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"})
    session.put.side_effect = [response(308), response(308, headers={"Range": "bytes=0-4"}), response(201, {"id": "resumed"})]
    monkeypatch.setattr(publish, "_youtube_session", lambda: session)
    assert publish.publish_episode(episode, youtube_config)["youtube"]["status"] == "pending"
    assert publish.publish_episode(episode, youtube_config)["youtube"]["status"] == "succeeded"
    assert session.put.call_args.kwargs["headers"]["Content-Range"] == "bytes 5-9/10"
    session.post.assert_called_once()


def test_changed_episode_does_not_overwrite_success(episode, youtube_config, monkeypatch):
    session = Mock()
    session.post.return_value = response(headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=x"})
    session.put.return_value = response(201, {"id": "already-done"})
    monkeypatch.setattr(publish, "_youtube_session", lambda: session)
    publish.publish_episode(episode, youtube_config)
    (episode / "vertical.mp4").write_bytes(b"different-video")
    result = publish.publish_episode(episode, youtube_config)
    assert result["youtube"]["status"] == "conflict"
    ledger = publish.PublicationLedger(Path(youtube_config["paths"]["state_db"]))
    assert ledger.get("2026-11-05-test", "youtube")["status"] == "succeeded"
    ledger.close()


def test_concurrent_claim_keeps_existing_lease(tmp_path):
    one = publish.PublicationLedger(tmp_path / "state.sqlite3")
    two = publish.PublicationLedger(tmp_path / "state.sqlite3")
    assert one.claim("e", "youtube", "sha")
    assert two.claim("e", "youtube", "sha") is None
    assert two.get("e", "youtube")["lease_until"] > publish.time.time()
    one.close()
    two.close()


def test_tiktok_exports_without_api_calls(episode, youtube_config, monkeypatch):
    youtube_config["publishing"]["platforms"] = ["tiktok"]
    session = Mock()
    monkeypatch.setattr(publish.requests, "Session", session)
    result = publish.publish_episode(episode, youtube_config)
    assert result["tiktok"]["status"] == "export_only"
    assert (episode / "tiktok-export.json").is_file()
    session.assert_not_called()


@pytest.fixture
def instagram_config(youtube_config, monkeypatch):
    for name, value in {"IG_USER_ID": "1234", "IG_ACCESS_TOKEN": "ig-secret", "MEDIA_BASE_URL": "https://media.example.com"}.items():
        monkeypatch.setenv(name, value)
    youtube_config["publishing"] = {"platforms": ["instagram"], "instagram": {"poll_attempts": 1, "refresh_long_lived_token": False}}
    return youtube_config


def test_instagram_container_then_publish(episode, instagram_config, monkeypatch):
    session = Mock()
    session.headers = {}
    session.post.side_effect = [response(payload={"id": "5432"}), response(payload={"id": "9999"})]
    session.get.return_value = response(payload={"status_code": "FINISHED"})
    monkeypatch.setattr(publish.requests, "Session", lambda: session)
    monkeypatch.setattr(publish.requests, "head", lambda *args, **kwargs: response())
    first = publish.publish_episode(episode, instagram_config)
    second = publish.publish_episode(episode, instagram_config)
    assert first["instagram"]["status"] == second["instagram"]["status"] == "succeeded"
    assert session.post.call_count == 2
    assert session.post.call_args.kwargs["data"] == {"creation_id": "5432"}
    assert session.post.call_args_list[0].kwargs["data"]["video_url"].endswith("/2026-11-05-test/vertical.mp4")


def test_instagram_lost_publish_response_never_sends_second_post(episode, instagram_config, monkeypatch):
    session = Mock()
    session.headers = {}
    session.post.side_effect = [response(payload={"id": "5432"}), requests.Timeout("ig-secret")]
    session.get.return_value = response(payload={"status_code": "FINISHED"})
    monkeypatch.setattr(publish.requests, "Session", lambda: session)
    monkeypatch.setattr(publish.requests, "head", lambda *args, **kwargs: response())
    assert publish.publish_episode(episode, instagram_config)["instagram"]["status"] == "uncertain"
    assert publish.publish_episode(episode, instagram_config)["instagram"]["status"] == "uncertain"
    assert session.post.call_count == 2
    session.get.return_value = response(payload={"status_code": "PUBLISHED"})
    assert publish.publish_episode(episode, instagram_config)["instagram"]["status"] == "succeeded"
    assert session.post.call_count == 2


def test_instagram_processing_reuses_container(episode, instagram_config, monkeypatch):
    session = Mock()
    session.headers = {}
    session.post.side_effect = [response(payload={"id": "5432"}), response(payload={"id": "9999"})]
    session.get.side_effect = [response(payload={"status_code": "IN_PROGRESS"}), response(payload={"status_code": "FINISHED"})]
    monkeypatch.setattr(publish.requests, "Session", lambda: session)
    monkeypatch.setattr(publish.requests, "head", lambda *args, **kwargs: response())
    assert publish.publish_episode(episode, instagram_config)["instagram"]["status"] == "pending"
    assert publish.publish_episode(episode, instagram_config)["instagram"]["status"] == "succeeded"
    assert session.post.call_count == 2


def test_media_directory_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_BASE_URL", "https://media.example.com")
    monkeypatch.setenv("MEDIA_UPLOAD_DIR", str(tmp_path / "webroot"))
    monkeypatch.delenv("MEDIA_S3_BUCKET", raising=False)
    video = tmp_path / "source.mp4"
    video.write_bytes(b"mp4")
    assert publish._public_media("episode-1", video) == "https://media.example.com/episode-1/vertical.mp4"
    assert (tmp_path / "webroot/episode-1/vertical.mp4").read_bytes() == b"mp4"
    with pytest.raises(publish.PublishError, match="invalide"):
        publish._public_media("../escape", video)


def test_instagram_token_refresh_is_cached_and_seed_rotation_wins(tmp_path, monkeypatch):
    ledger = publish.PublicationLedger(tmp_path / "tokens.sqlite3")
    fetch = Mock(side_effect=[response(payload={"access_token": "refreshed1"}),
                             response(payload={"access_token": "refreshed2"})])
    monkeypatch.setattr(publish.requests, "get", fetch)
    assert publish._instagram_token("seed1", ledger) == "refreshed1"
    assert publish._instagram_token("seed1", ledger) == "refreshed1"
    assert fetch.call_count == 1
    assert publish._instagram_token("seed2", ledger) == "refreshed2"
    assert fetch.call_count == 2
    ledger.close()


def test_instagram_young_token_retry_after_a_day(tmp_path, monkeypatch):
    ledger = publish.PublicationLedger(tmp_path / "tokens.sqlite3")
    now = [1000000.0]
    monkeypatch.setattr(publish.time, "time", lambda: now[0])
    fetch = Mock(side_effect=[response(400), response(payload={"access_token": "renewed"})])
    monkeypatch.setattr(publish.requests, "get", fetch)
    assert publish._instagram_token("new-seed", ledger) == "new-seed"
    assert publish._instagram_token("new-seed", ledger) == "new-seed"
    assert fetch.call_count == 1
    now[0] += 86401
    assert publish._instagram_token("new-seed", ledger) == "renewed"
    assert fetch.call_count == 2
    ledger.close()
