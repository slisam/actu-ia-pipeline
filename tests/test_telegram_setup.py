"""La connexion au bot ne publie rien et ne révèle aucun jeton."""
from unittest.mock import Mock

import pytest
import requests

from pipelineia import telegram_setup as setup


def test_private_chat_lookup_only_returns_ids_and_does_not_ack_updates(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:abcdefghijklmnopqrstuvwx")
    get = Mock(return_value=Mock(status_code=200, json=lambda: {"ok": True, "result": [
        {"message": {"chat": {"id": 1234, "type": "private"}, "text": "private-message"}},
        {"message": {"chat": {"id": -100123, "type": "group"}}},
        {"message": {"chat": {"id": 1234, "type": "private"}}},
    ]}))
    monkeypatch.setattr(setup.requests, "get", get)
    assert setup.private_chat_ids() == ["1234"]
    assert get.call_args.kwargs["allow_redirects"] is False
    assert "offset" not in get.call_args.kwargs["params"]


def test_missing_token_makes_no_network_call(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    get = Mock()
    monkeypatch.setattr(setup.requests, "get", get)
    with pytest.raises(setup.TelegramSetupError):
        setup.private_chat_ids()
    get.assert_not_called()


def test_setup_transport_error_never_displays_token(monkeypatch):
    token = "123456:abcdefghijklmnopqrstuvwx"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(setup.requests, "get", Mock(side_effect=requests.Timeout(token)))
    with pytest.raises(setup.TelegramSetupError) as caught:
        setup.private_chat_ids()
    assert token not in str(caught.value)
