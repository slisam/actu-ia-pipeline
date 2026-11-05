"""Envoi, déduplication, reprise et confidentialité des alertes, sans réseau réel."""
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
import requests

from pipelineia import alerts

EPISODE = "2026-11-05-actu-ia"
TOKEN = "123456789:" + "a" * 32


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
    return {"paths": {"state_db": str(tmp_path / "state.sqlite3")},
            "alerts": {"enabled": True, "cooldown_seconds": 3600,
                       "retry_base_seconds": 10, "max_attempts": 3,
                       "pending_delay_seconds": 900}}


@pytest.fixture
def clock(monkeypatch):
    value = [1_800_000_000.0]
    monkeypatch.setattr(alerts.time, "time", lambda: value[0])
    return value


@pytest.fixture
def post(monkeypatch):
    value = Mock(return_value=response())
    monkeypatch.setattr(alerts.requests, "post", value)
    return value


def response(status=200, body=None):
    return Mock(status_code=status, json=Mock(return_value={"ok": True} if body is None else body))


def rows(config):
    with sqlite3.connect(config["paths"]["state_db"]) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM alerts ORDER BY id")]


def test_success_uses_private_telegram_and_no_paid_broadcast(config, post):
    result = alerts.notify_failure(config, EPISODE, "voice", "quota")
    assert result["status"] == "sent"
    post.assert_called_once()
    assert post.call_args.args == (f"https://api.telegram.org/bot{TOKEN}/sendMessage",)
    body = post.call_args.kwargs["json"]
    assert body["chat_id"] == "123456789" and "Voix off" in body["text"]
    assert body["allow_paid_broadcast"] is False
    assert "parse_mode" not in body
    assert post.call_args.kwargs["allow_redirects"] is False
    assert TOKEN not in Path(config["paths"]["state_db"]).read_bytes().decode("latin1")


def test_missing_credentials_remain_queued_then_deliver(config, post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert alerts.notify_failure(config, EPISODE, "write", "quota")["status"] == "pending"
    assert rows(config)[0]["attempts"] == 0
    post.assert_not_called()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert alerts.flush_alerts(config)["sent"] == 1
    assert rows(config)[0]["status"] == "sent"


def test_repeats_and_new_flushes_do_not_duplicate_delivery(config, post, clock):
    for _ in range(6):
        alerts.notify_failure(config, EPISODE, "render", "failed")
        alerts.flush_alerts(config)
    assert post.call_count == 1
    assert rows(config)[0]["occurrences"] == 6
    clock[0] += 3601
    alerts.notify_failure(config, EPISODE, "render", "failed")
    assert post.call_count == 2


def test_resolve_cancels_queued_messages_before_connection(config, post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    alerts.notify_failure(config, EPISODE, "voice", "failed")
    alerts.resolve_episode(config, EPISODE)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    assert alerts.flush_alerts(config)["sent"] == 0
    post.assert_not_called()
    assert rows(config)[0]["resolved"] == 1


def test_new_incident_after_recovery_sends_without_old_cooldown(config, post, clock):
    alerts.notify_failure(config, EPISODE, "voice", "failed")
    alerts.resolve_episode(config, EPISODE)
    alerts.notify_failure(config, EPISODE, "voice", "failed")
    assert post.call_count == 2
    assert rows(config)[0]["resolved"] == 0


def test_pending_delay_is_not_postponed_by_repeated_observations(config, post, clock):
    alerts.notify_failure(config, EPISODE, "publish", "pending", "instagram")
    clock[0] += 800
    alerts.notify_failure(config, EPISODE, "publish", "pending", "instagram")
    post.assert_not_called()
    clock[0] += 101
    assert alerts.flush_alerts(config)["sent"] == 1


def test_recovered_pending_does_not_deliver_after_delay(config, post, clock):
    alerts.notify_failure(config, EPISODE, "publish", "pending", "instagram")
    alerts.resolve_episode(config, EPISODE)
    clock[0] += 901
    alerts.flush_alerts(config)
    post.assert_not_called()


def test_new_event_does_not_flush_other_episode_before_it_recovers(config, post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    alerts.notify_failure(config, EPISODE, "write", "failed")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    alerts.notify_failure(config, "2026-11-06-actu-ia", "voice", "failed")
    assert post.call_count == 1
    assert "2026-11-06" in post.call_args.kwargs["json"]["text"]


def test_telegram_retry_after_is_persistent_and_respected(config, post, clock):
    post.side_effect = [response(429, {"ok": False, "parameters": {"retry_after": 120}}), response()]
    assert alerts.notify_failure(config, EPISODE, "write", "failed")["status"] == "pending"
    alerts.flush_alerts(config)
    assert post.call_count == 1
    clock[0] += 121
    assert alerts.flush_alerts(config)["sent"] == 1
    assert post.call_count == 2


def test_rate_limited_retries_stop_at_configured_maximum(config, post, clock):
    post.return_value = response(429, {"ok": False, "parameters": {"retry_after": 1}})
    alerts.notify_failure(config, EPISODE, "write", "failed")
    for _ in range(8):
        clock[0] += 100
        alerts.flush_alerts(config)
    assert post.call_count == 3
    assert rows(config)[0]["status"] == "failed"


def test_uncertain_delivery_is_not_repeated_after_timeout(config, post, clock, caplog):
    post.side_effect = requests.Timeout("private-token-and-url")
    with caplog.at_level(logging.WARNING):
        assert alerts.notify_failure(config, EPISODE, "voice", "uncertain")["status"] == "uncertain"
        clock[0] += 100000
        alerts.notify_failure(config, EPISODE, "voice", "uncertain")
        alerts.flush_alerts(config)
    assert post.call_count == 1
    assert "private-token-and-url" not in caplog.text
    assert b"private-token-and-url" not in Path(config["paths"]["state_db"]).read_bytes()


@pytest.mark.parametrize("status,body", [(500, {"description": "secret-error-body"}),
                                        (200, ["secret-error-body"])])
def test_server_or_unknown_result_is_uncertain(config, post, status, body):
    post.return_value = response(status, body)
    assert alerts.notify_failure(config, EPISODE, "render", "failed")["status"] == "uncertain"
    alerts.flush_alerts(config)
    assert post.call_count == 1
    assert b"secret-error-body" not in Path(config["paths"]["state_db"]).read_bytes()


def test_explicit_refusal_is_terminal_without_body_exposure(config, post, caplog):
    post.return_value = response(403, {"ok": False, "description": "secret-error-body"})
    with caplog.at_level(logging.WARNING):
        assert alerts.notify_failure(config, EPISODE, "write", "failed")["status"] == "failed"
    alerts.flush_alerts(config)
    assert post.call_count == 1
    assert b"secret-error-body" not in Path(config["paths"]["state_db"]).read_bytes()
    assert "secret-error-body" not in caplog.text


def test_corrected_telegram_credentials_retry_explicit_refusal(config, post, monkeypatch):
    post.side_effect = [response(401, {"ok": False}), response()]
    assert alerts.notify_failure(config, "test", "startup", "test")["status"] == "failed"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "987654321:" + "b" * 32)
    assert alerts.notify_failure(config, "test", "startup", "test")["status"] == "sent"
    assert post.call_count == 2
    assert rows(config)[0]["attempts"] == 1
    assert TOKEN not in Path(config["paths"]["state_db"]).read_bytes().decode("latin1")


def test_corrected_route_never_retries_uncertain_delivery(config, post, monkeypatch):
    post.side_effect = requests.Timeout("unknown outcome")
    assert alerts.notify_failure(config, "test", "startup", "test")["status"] == "uncertain"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "987654321:" + "b" * 32)
    assert alerts.notify_failure(config, "test", "startup", "test")["status"] == "uncertain"
    assert post.call_count == 1


def test_unknown_inputs_never_become_notification_content(config, post):
    secret = "https://private.invalid/?api_key=secret-sensitive-value"
    alerts.notify_failure(config, secret, secret, secret, secret)
    assert "secret-sensitive-value" not in post.call_args.kwargs["json"]["text"]
    assert b"secret-sensitive-value" not in Path(config["paths"]["state_db"]).read_bytes()


def test_simultaneous_reports_claim_one_delivery(config, post):
    entered, release = Event(), Event()
    def deliver(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return response()
    post.side_effect = deliver
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(alerts.notify_failure, config, EPISODE, "voice", "failed")
        assert entered.wait(5)
        second = executor.submit(alerts.notify_failure, config, EPISODE, "voice", "failed")
        assert second.result(timeout=5)["status"] == "sending"
        release.set()
        assert first.result(timeout=5)["status"] == "sent"
    assert post.call_count == 1 and rows(config)[0]["occurrences"] == 2


def test_stale_claim_is_uncertain_not_resent(config, post, clock):
    alerts.notify_failure(config, EPISODE, "voice", "failed")
    with sqlite3.connect(config["paths"]["state_db"]) as db:
        db.execute("UPDATE alerts SET status='sending',lease_until=?,claim='old'", (clock[0] - 1,))
    alerts.flush_alerts(config)
    assert rows(config)[0]["status"] == "uncertain"
    assert post.call_count == 1


@pytest.mark.parametrize("chat", ["-12345", "@group", "12345/path", "", "0"])
def test_private_positive_chat_only(config, post, monkeypatch, chat):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", chat)
    assert not alerts.alert_readiness(config)["ready"]
    alerts.notify_failure(config, EPISODE, "voice", "failed")
    post.assert_not_called()


def test_absent_or_disabled_configuration_does_not_create_database(config, post):
    config.pop("alerts")
    assert alerts.notify_failure(config, EPISODE, "write")["status"] == "disabled"
    assert alerts.flush_alerts(config)["status"] == "disabled"
    alerts.resolve_episode(config, EPISODE)
    assert not Path(config["paths"]["state_db"]).exists()
    post.assert_not_called()


def test_readiness_never_contacts_telegram_or_creates_journal(config, post):
    assert alerts.alert_readiness(config)["ready"]
    assert not Path(config["paths"]["state_db"]).exists()
    post.assert_not_called()


def test_broken_journal_never_raises_or_logs_exception_secret(config, post, caplog, monkeypatch):
    monkeypatch.setattr(alerts, "_path", Mock(side_effect=RuntimeError("secret-in-error")))
    with caplog.at_level(logging.WARNING):
        assert alerts.notify_failure(config, EPISODE, "write")["status"] == "unavailable"
        assert alerts.flush_alerts(config)["status"] == "unavailable"
        alerts.resolve_episode(config, EPISODE)
    assert "secret-in-error" not in caplog.text
    post.assert_not_called()
