"""Bascule immédiate entre projets, sans réessayer leurs clés en pause."""

import copy
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from pipelineia import llm_pool as pool
from pipelineia import writer
from tests.test_writer import ARTICLES, valid_script, verification


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Quatre projets indépendants et aucune requête réseau réelle."""
    for number in range(4):
        monkeypatch.setenv(f"PROJECT_SWITCH_KEY_{number}", f"fake-project-key-{number}")
    return {
        "paths": {"state_db": str(tmp_path / "quota.sqlite3")},
        "llm": {
            "provider": "api_pool", "model": "gemini-test",
            "daily_request_limit": 12, "max_http_attempts_per_run": 8,
            "max_requests_per_run": 4,
            "api_pool": [
                {"id": f"slot_{number}", "provider": "gemini",
                 "api_key_env": f"PROJECT_SWITCH_KEY_{number}",
                 "quota_group": f"independent-project-{number}",
                 "free_tier_confirmed": True}
                for number in range(4)
            ],
        },
    }


def reply(status=200, value=None, headers=None):
    """Simule la structure publique de generateContent."""
    payload = ({"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": json.dumps(value if value is not None else {"ok": True})}
    ]}}]} if status == 200 else (value or {}))
    return Mock(status_code=status, headers=headers or {}, json=Mock(return_value=payload))


def called_keys(post):
    return [call.kwargs["headers"]["x-goog-api-key"] for call in post.call_args_list]


def test_multiple_exhausted_projects_switch_immediately_to_next_available(settings, monkeypatch):
    post = Mock(side_effect=[reply(429), reply(429), reply(value={"third": "ready"})])
    monkeypatch.setattr(pool.requests, "post", post)
    monkeypatch.setattr(pool.time, "sleep", Mock(side_effect=AssertionError("Pas d'attente entre projets")))
    assert pool.APIPool(settings).generate("Annonce sourcée") == {"third": "ready"}
    assert called_keys(post) == [f"fake-project-key-{i}" for i in range(3)]


def test_all_projects_exhausted_do_not_send_more_requests_until_reset(settings, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr(pool.time, "time", lambda: clock[0])
    post = Mock(return_value=reply(429, headers={"Retry-After": "180"}))
    monkeypatch.setattr(pool.requests, "post", post)
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(settings).generate("Annonce")
    assert post.call_count == 4
    with pytest.raises(pool.QuotaExhausted):
        pool.APIPool(settings).generate("Reprise avant le renouvellement")
    assert post.call_count == 4
    clock[0] += 181
    post.return_value = reply()
    assert pool.APIPool(settings).generate("Reprise autorisée") == {"ok": True}
    assert post.call_count == 5


def test_same_project_alias_is_skipped_after_quota_but_another_project_runs(settings, monkeypatch):
    settings["llm"]["api_pool"][1]["quota_group"] = settings["llm"]["api_pool"][0]["quota_group"]
    post = Mock(side_effect=[reply(429), reply()])
    monkeypatch.setattr(pool.requests, "post", post)
    assert pool.APIPool(settings).generate("Annonce") == {"ok": True}
    assert called_keys(post) == ["fake-project-key-0", "fake-project-key-2"]


def test_restart_preserves_exhausted_project_and_does_not_retry_it(settings, monkeypatch):
    post = Mock(side_effect=[reply(429), reply(), reply()])
    monkeypatch.setattr(pool.requests, "post", post)
    pool.APIPool(settings).generate("Rédaction")
    pool.APIPool(copy.deepcopy(settings)).generate("Vérification")
    assert called_keys(post) == ["fake-project-key-0", "fake-project-key-1", "fake-project-key-1"]


def test_writer_verifies_with_the_project_that_remains_available(settings, monkeypatch):
    script = valid_script()
    post = Mock(side_effect=[reply(429), reply(value=script), reply(value=verification(script))])
    monkeypatch.setattr(pool.requests, "post", post)
    result = writer.write_script(ARTICLES, settings)
    assert result["verification"]["supported"] is True
    assert result["llm_requests"] == 2
    assert result["llm_http_attempts"] == 3
    assert called_keys(post) == ["fake-project-key-0", "fake-project-key-1", "fake-project-key-1"]


def test_retry_after_is_scoped_to_one_project_and_rechecked_when_elapsed(settings, monkeypatch):
    clock = [1_800_000_000.0]
    monkeypatch.setattr(pool.time, "time", lambda: clock[0])
    post = Mock(side_effect=[reply(429, headers={"Retry-After": "120"}), reply(), reply(), reply()])
    monkeypatch.setattr(pool.requests, "post", post)
    pool.APIPool(settings).generate("Premier appel")
    clock[0] += 119
    pool.APIPool(settings).generate("Pendant la pause du premier projet")
    clock[0] += 2
    pool.APIPool(settings).generate("Après sa pause")
    assert called_keys(post) == ["fake-project-key-0", "fake-project-key-1", "fake-project-key-1", "fake-project-key-0"]


def test_daily_quota_blocks_only_its_project_until_pacific_midnight(settings, monkeypatch):
    clock = [datetime(2026, 11, 5, 20, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(pool.time, "time", lambda: clock[0])
    daily_error = {"error": {"details": [{"quotaId": "GenerateRequestsPerDay"}, {"retryDelay": "10s"}]}}
    post = Mock(side_effect=[reply(429, daily_error), reply(), reply(), reply()])
    monkeypatch.setattr(pool.requests, "post", post)
    pool.APIPool(settings).generate("Annonce")
    clock[0] = datetime(2026, 11, 6, 7, 59, tzinfo=timezone.utc).timestamp()
    pool.APIPool(settings).generate("Avant minuit Pacific")
    clock[0] = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc).timestamp()
    pool.APIPool(settings).generate("Après minuit Pacific")
    assert called_keys(post) == ["fake-project-key-0", "fake-project-key-1", "fake-project-key-1", "fake-project-key-0"]


def test_old_global_pause_does_not_block_unrelated_projects_after_upgrade(settings, monkeypatch):
    api = pool.APIPool(settings)
    with sqlite3.connect(settings["paths"]["state_db"]) as db:
        db.execute("CREATE TABLE IF NOT EXISTS llm_app_quota (id INTEGER PRIMARY KEY, blocked_until REAL NOT NULL)")
        db.execute("INSERT OR REPLACE INTO llm_app_quota VALUES(1,?)", (pool.time.time() + 86_400,))
    post = Mock(return_value=reply())
    monkeypatch.setattr(pool.requests, "post", post)
    assert pool.APIPool(settings).generate("Projet disponible après mise à jour") == {"ok": True}
    assert post.call_count == 1


def test_upgrade_preserves_existing_project_cooldown_and_application_usage(settings, monkeypatch):
    """La migration d'une base ancienne conserve délais et compteurs déjà connus."""
    now = 1_800_000_000.0
    monkeypatch.setattr(pool.time, "time", lambda: now)
    with sqlite3.connect(settings["paths"]["state_db"]) as db:
        db.execute("CREATE TABLE llm_project_cooldown (project TEXT PRIMARY KEY, until_time REAL NOT NULL)")
        db.execute("INSERT INTO llm_project_cooldown VALUES(?,?)", ("independent-project-0", now + 300))
        db.execute("CREATE TABLE llm_daily_usage (day TEXT, scope TEXT, attempts INTEGER, PRIMARY KEY(day,scope))")
        db.execute("INSERT INTO llm_daily_usage VALUES(?,?,2)", (pool._day(now), "application"))
    post = Mock(return_value=reply())
    monkeypatch.setattr(pool.requests, "post", post)
    assert pool.APIPool(settings).generate("Après mise à jour") == {"ok": True}
    assert called_keys(post) == ["fake-project-key-1"]
    with sqlite3.connect(settings["paths"]["state_db"]) as db:
        assert db.execute("SELECT attempts FROM llm_daily_usage WHERE scope='application'").fetchone()[0] == 3
