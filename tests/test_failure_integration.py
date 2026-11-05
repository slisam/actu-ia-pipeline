"""Le transport d'alerte ne doit ni divulguer des secrets ni modifier un échec métier."""
import json
import logging
from unittest.mock import Mock

import pytest

from pipelineia import failures
from pipelineia import __main__ as cli
from pipelineia.elevenlabs import ElevenLabsError
from pipelineia.llm_pool import QuotaExhausted
from pipelineia.writer import WriterError
from tests.test_run import pipeline


@pytest.mark.parametrize("stage,exception,code", [
    ("write", WriterError("Aucune clé gratuite configurée"), "credentials"),
    ("write", QuotaExhausted("secret-body"), "quota"),
    ("voice", ElevenLabsError("Crédits ou quota ElevenLabs indisponibles"), "quota"),
    ("voice", ElevenLabsError("Génération précédente ambiguë : vérifier l'historique"), "uncertain"),
    ("voice", ElevenLabsError("Renseigner ELEVENLABS_VOICE_ID"), "credentials"),
    ("render", RuntimeError("?access_token=secret"), "failed"),
    ("startup", ValueError("private-path-secret"), "configuration"),
])
def test_classification_sends_only_a_fixed_code(stage, exception, code, monkeypatch):
    send = Mock()
    monkeypatch.setattr(failures, "notify_failure", send)
    failures.report_failure({}, "2026-11-05-actu-ia", stage, exception)
    send.assert_called_once_with({}, "2026-11-05-actu-ia", stage, code=code)
    assert exception._pipeline_alert_handled is True


@pytest.mark.parametrize("boundary,stage", [("collect", "collect"), ("writer", "write"),
                                           ("speech", "voice"), ("renderer", "render"),
                                           ("publisher", "publish")])
def test_every_production_stage_notifies_without_masking_original_failure(pipeline, monkeypatch, boundary, stage):
    from pipelineia import run
    original = RuntimeError("private-provider-body")
    pipeline[boundary].side_effect = original
    send = Mock()
    monkeypatch.setattr(failures, "notify_failure", send)
    with pytest.raises(RuntimeError) as caught:
        run.run_episode(pipeline["config"], publish=True)
    assert caught.value is original
    send.assert_called_once_with(pipeline["config"], "2026-11-05-actu-ia", stage, code="failed")


def test_broken_alert_module_cannot_replace_voice_failure(pipeline, monkeypatch):
    from pipelineia import run
    original = ElevenLabsError("Crédits indisponibles")
    pipeline["speech"].side_effect = original
    monkeypatch.setattr(failures, "notify_failure", Mock(side_effect=RuntimeError("transport-secret")))
    with pytest.raises(ElevenLabsError) as caught:
        run.run_episode(pipeline["config"])
    assert caught.value is original


def test_partial_publication_alerts_only_destinations_in_difficulty(pipeline, monkeypatch):
    from pipelineia import run
    pipeline["publisher"].return_value = {
        "youtube": {"status": "succeeded"},
        "instagram": {"status": "uncertain", "error": "secret-access-token"},
        "tiktok": {"status": "export_only"},
    }
    send = Mock()
    monkeypatch.setattr(failures, "notify_failure", send)
    result = run.run_episode(pipeline["config"], publish=True)
    assert result["status"] == "publication_incomplete"
    send.assert_called_once_with(pipeline["config"], "2026-11-05-actu-ia", "publish", code="uncertain", platform="instagram")


def test_pending_publication_uses_delayed_code(pipeline, monkeypatch):
    from pipelineia import run
    pipeline["publisher"].return_value = {"youtube": {"status": "pending"}}
    send = Mock()
    monkeypatch.setattr(failures, "notify_failure", send)
    run.run_episode(pipeline["config"], publish=True)
    assert send.call_args.kwargs == {"code": "pending", "platform": "youtube"}


def test_success_resolves_old_alerts(pipeline, monkeypatch):
    from pipelineia import run
    resolve = Mock()
    monkeypatch.setattr(failures, "resolve_episode", resolve)
    result = run.run_episode(pipeline["config"])
    assert result["status"] == "complete"
    resolve.assert_called_once_with(pipeline["config"], result["episode_id"])


def test_no_news_and_demo_failures_do_not_send_alerts(pipeline, monkeypatch):
    from pipelineia import run
    send = Mock()
    monkeypatch.setattr(failures, "notify_failure", send)
    pipeline["collect"].return_value = []
    assert run.run_episode(pipeline["config"])["status"] == "no_news"
    pipeline["speech"].side_effect = RuntimeError("example")
    with pytest.raises(RuntimeError):
        run.run_episode(pipeline["config"], demo=True)
    send.assert_not_called()


def test_writer_wrapped_quota_keeps_failure_category():
    try:
        try:
            raise QuotaExhausted("quota")
        except QuotaExhausted:
            raise WriterError("Aucun autre projet disponible") from None
    except WriterError as exc:
        assert failures.failure_code("write", exc) == "quota"


def test_real_alert_journal_deduplicates_then_resolves_recovered_episode(pipeline, monkeypatch):
    from pipelineia import alerts, run
    pipeline["config"]["alerts"] = {"enabled": True}
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwx")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234567")
    post = Mock(return_value=Mock(status_code=200, json=lambda: {"ok": True}))
    monkeypatch.setattr(alerts.requests, "post", post)
    pipeline["writer"].side_effect = WriterError("Aucune clé gratuite configurée")
    for _ in range(2):
        with pytest.raises(WriterError):
            run.run_episode(pipeline["config"])
    assert post.call_count == 1
    pipeline["writer"].side_effect = None
    run.run_episode(pipeline["config"])
    import sqlite3
    with sqlite3.connect(pipeline["config"]["paths"]["state_db"]) as db:
        assert db.execute("SELECT resolved FROM alerts").fetchone()[0] == 1


def test_publication_recovers_before_pending_alert_is_due(pipeline, monkeypatch):
    from pipelineia import alerts, run
    pipeline["config"]["alerts"] = {"enabled": True, "pending_delay_seconds": 900}
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwx")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234567")
    clock = [1_800_000_000.0]
    monkeypatch.setattr(alerts.time, "time", lambda: clock[0])
    post = Mock(return_value=Mock(status_code=200, json=lambda: {"ok": True}))
    monkeypatch.setattr(alerts.requests, "post", post)
    pipeline["publisher"].return_value = {"youtube": {"status": "pending"}}
    run.run_episode(pipeline["config"], publish=True)
    clock[0] += 901
    pipeline["publisher"].return_value = {"youtube": {"status": "succeeded"}}
    run.run_episode(pipeline["config"], publish=True)
    alerts.flush_alerts(pipeline["config"])
    post.assert_not_called()
