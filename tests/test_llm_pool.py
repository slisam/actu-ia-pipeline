"""Contrats HTTP, quotas globaux et confidentialité du pool Gemini."""
import copy
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests

from pipelineia import llm_pool as pool


@pytest.fixture
def config(tmp_path, monkeypatch):
    for index in range(4):
        monkeypatch.setenv(f"TEST_POOL_KEY_{index}", f"secret-key-{index}")
    return {"paths": {"state_db": str(tmp_path / "state.sqlite3")},
            "llm": {"model": "gemini-test", "daily_request_limit": 12,
                    "max_http_attempts_per_run": 8,
                    "api_pool": [{"id": f"slot_{i}", "provider": "gemini",
                                  "api_key_env": f"TEST_POOL_KEY_{i}",
                                  "quota_group": f"real-project-{i}", "free_tier_confirmed": True}
                                 for i in range(4)]}}


def response(code=200, body=None, headers=None):
    return Mock(status_code=code, headers=headers or {}, json=Mock(return_value=body if body is not None else {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"ok":true}'}]}}]}))


def test_success_contract_and_no_redirect(config, monkeypatch):
    post = Mock(return_value=response())
    monkeypatch.setattr(pool.requests, "post", post)
    api = pool.APIPool(config)
    assert api.generate("Texte public") == {"ok": True}
    assert api.requests == 1
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["headers"] == {"x-goog-api-key": "secret-key-0"}
    assert post.call_args.kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_429_pauses_different_projects_and_survives_restart(config, monkeypatch):
    now = [1_800_000_000.0]
    monkeypatch.setattr(pool.time, "time", lambda: now[0])
    post = Mock(return_value=response(429, {}, {"Retry-After": "120"}))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(config).generate("Annonce")
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(config).generate("Autre annonce")
    assert post.call_count == 1  # Aucune rotation vers les trois autres projets.
    now[0] += 121
    post.return_value = response()
    assert pool.APIPool(config).generate("Reprise") == {"ok": True}
    assert post.call_count == 2


def test_same_project_keys_cannot_prolong_quota(config, monkeypatch):
    for slot in config["llm"]["api_pool"]:
        slot["quota_group"] = "one-real-project"
    post = Mock(return_value=response(429, {}))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(config).generate("Annonce")
    assert post.call_count == 1


def test_daily_budget_shared_between_keys_instances_and_failed_requests(config, monkeypatch):
    config["llm"]["daily_request_limit"] = 2
    post = Mock(side_effect=[response(401, {}), response()])
    monkeypatch.setattr(pool.requests, "post", post)
    assert pool.APIPool(config).generate("Texte") == {"ok": True}
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(config).generate("Encore")
    assert post.call_count == 2


def test_http_budget_not_reset_between_generations(config, monkeypatch):
    config["llm"]["max_http_attempts_per_run"] = 2
    post = Mock(return_value=response())
    monkeypatch.setattr(pool.requests, "post", post)
    api = pool.APIPool(config)
    api.generate("Rédaction")
    api.generate("Vérification")
    with pytest.raises(pool.PoolError, match="Budget"):
        api.generate("Correction")
    assert post.call_count == 2


def test_invalid_credential_uses_next_and_stays_disabled(config, monkeypatch):
    post = Mock(side_effect=[response(400, {"error": {"reason": "API_KEY_INVALID"}}), response(), response()])
    monkeypatch.setattr(pool.requests, "post", post)
    pool.APIPool(config).generate("Rédaction")
    pool.APIPool(config).generate("Vérification")
    keys = [call.kwargs["headers"]["x-goog-api-key"] for call in post.call_args_list]
    assert keys == ["secret-key-0", "secret-key-1", "secret-key-1"]


def test_rotation_of_rejected_key_unblocks_new_credential(config, monkeypatch):
    post = Mock(side_effect=[response(401, {}), response(), response()])
    monkeypatch.setattr(pool.requests, "post", post)
    pool.APIPool(config).generate("Texte")
    monkeypatch.setenv("TEST_POOL_KEY_0", "new-credential")
    pool.APIPool(config).generate("Texte")
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "new-credential"


def test_prompt_error_does_not_try_another_key(config, monkeypatch):
    post = Mock(return_value=response(400, {"error": {"message": "input too long"}}))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.PoolError, match="HTTP 400"):
        pool.APIPool(config).generate("Texte")
    assert post.call_count == 1


def test_network_error_uses_bounded_fallback(config, monkeypatch):
    post = Mock(side_effect=[requests.Timeout("secret-key-0"), response()])
    monkeypatch.setattr(pool.requests, "post", post)
    api = pool.APIPool(config)
    assert api.generate("Texte") == {"ok": True}
    assert api.requests == 2


def test_all_network_errors_bounded_to_four_requests(config, monkeypatch):
    post = Mock(side_effect=requests.ConnectionError("secret endpoint"))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.PoolError) as caught:
        pool.APIPool(config).generate("Texte")
    assert post.call_count == 4
    assert "secret endpoint" not in str(caught.value)


@pytest.mark.parametrize("change", ["unconfirmed", "missing", "placeholder", "unsafe-model", "wrong-provider"])
def test_unready_slots_never_send_requests(config, monkeypatch, change):
    config["llm"]["api_pool"] = config["llm"]["api_pool"][:1]
    slot = config["llm"]["api_pool"][0]
    if change == "unconfirmed":
        slot["free_tier_confirmed"] = False
    elif change == "missing":
        monkeypatch.delenv("TEST_POOL_KEY_0")
    elif change == "placeholder":
        slot["quota_group"] = "a-renseigner-projet-1"
    elif change == "unsafe-model":
        slot["model"] = "model?key=secret"
    else:
        slot["provider"] = "unknown"
    post = Mock()
    monkeypatch.setattr(pool.requests, "post", post)
    assert not pool.readiness(config)["slot_0"]["ready"]
    with pytest.raises(pool.PoolError):
        pool.APIPool(config)
    post.assert_not_called()


def test_readiness_has_no_db_network_or_secret_output(config, monkeypatch):
    monkeypatch.setattr(pool.requests, "post", Mock(side_effect=AssertionError("HTTP")))
    result = pool.readiness(config)
    assert all(item["ready"] for item in result.values())
    assert "secret-key" not in json.dumps(result)
    from pathlib import Path
    assert not Path(config["paths"]["state_db"]).exists()


def test_secret_never_persisted_or_returned(config, monkeypatch):
    post = Mock(return_value=response(401, {"message": "secret-key-0"}))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.PoolError) as caught:
        pool.APIPool(config).generate("secret-prompt")
    assert "secret-key" not in str(caught.value)
    with open(config["paths"]["state_db"], "rb") as stream:
        raw = stream.read()
    assert b"secret-key" not in raw and b"secret-prompt" not in raw


@pytest.mark.parametrize("text", ["not JSON", "[]", "{broken"])
def test_malformed_model_output_is_safe_value_error(config, monkeypatch, text):
    monkeypatch.setattr(pool.requests, "post", Mock(return_value=response(body={
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]})))
    with pytest.raises(ValueError):
        pool.APIPool(config).generate("Texte")


def test_truncated_output_never_accepted(config, monkeypatch):
    monkeypatch.setattr(pool.requests, "post", Mock(return_value=response(body={
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{}'}]}}]})))
    with pytest.raises(ValueError, match="interrompu"):
        pool.APIPool(config).generate("Texte")


def test_daily_quota_waits_until_pacific_midnight(config, monkeypatch):
    now = datetime(2026, 11, 5, 20, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(pool.time, "time", lambda: now)
    post = Mock(return_value=response(429, {"error": {"details": [{"quotaId": "GenerateRequestsPerDay"}, {"retryDelay": "10s"}]}}))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(config).generate("Texte")
    with sqlite3.connect(config["paths"]["state_db"]) as db:
        until = db.execute("SELECT blocked_until FROM llm_app_quota").fetchone()[0]
    assert until == datetime(2026, 11, 6, 8, tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("utc,expected", [("2026-07-05T06:59:00+00:00", "2026-07-04"),
                                          ("2026-07-05T07:00:00+00:00", "2026-07-05"),
                                          ("2026-11-05T07:59:00+00:00", "2026-11-04"),
                                          ("2026-11-05T08:00:00+00:00", "2026-11-05")])
def test_daily_boundary_tracks_pacific_dst(utc, expected):
    assert pool._day(datetime.fromisoformat(utc).timestamp()) == expected


def test_retry_after_http_date_and_retry_info_use_latest():
    now = datetime(2026, 11, 5, 10, tzinfo=timezone.utc).timestamp()
    result = pool._retry_at(response(429, {}, {"Retry-After": "Thu, 05 Nov 2026 10:05:00 GMT"}),
                            {"error": {"details": [{"retryDelay": "400.5s"}]}}, now)
    assert result == now + 400.5


def test_daily_cap_reservation_is_shared_across_existing_instances(config, monkeypatch):
    config["llm"]["daily_request_limit"] = 1
    first, second = pool.APIPool(config), pool.APIPool(config)
    post = Mock(return_value=response())
    monkeypatch.setattr(pool.requests, "post", post)
    first.generate("Premier épisode")
    with pytest.raises(pool.QuotaExhausted):
        second.generate("Autre processus")
    assert post.call_count == 1


@pytest.mark.parametrize("content", ["bad", {"parts": "bad"}, {"parts": [{"text": {"secret": "value"}}]}])
def test_malformed_api_structure_never_leaks_body(config, monkeypatch, content):
    monkeypatch.setattr(pool.requests, "post", Mock(return_value=response(body={
        "candidates": [{"finishReason": "STOP", "content": content}]})))
    with pytest.raises(ValueError, match="malformée"):
        pool.APIPool(config).generate("Texte")


def test_duplicate_id_cannot_authorize_unconfirmed_or_invalid_slot(config, monkeypatch):
    config["llm"]["api_pool"] = config["llm"]["api_pool"][:2]
    first, second = config["llm"]["api_pool"]
    first["free_tier_confirmed"] = False
    first["model"] = "unsafe/model"
    second["id"] = first["id"]
    post = Mock()
    monkeypatch.setattr(pool.requests, "post", post)
    assert pool.readiness(config)["slot_0"]["ready"] is False
    with pytest.raises(pool.PoolError):
        pool.APIPool(config)
    post.assert_not_called()
