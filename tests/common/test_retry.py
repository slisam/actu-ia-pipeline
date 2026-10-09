"""Tests du décorateur de retry."""

import pytest

from src.common.retry import retry_api


def test_retry_reussit_apres_echecs():
    appels = {"n": 0}

    @retry_api(tentatives=3, attente_min=0.01, attente_max=0.02)
    def instable() -> str:
        appels["n"] += 1
        if appels["n"] < 3:
            raise ConnectionError("panne")
        return "ok"

    assert instable() == "ok"
    assert appels["n"] == 3


def test_retry_abandonne():
    @retry_api(tentatives=2, attente_min=0.01, attente_max=0.02)
    def toujours_ko() -> None:
        raise ConnectionError("panne")

    with pytest.raises(ConnectionError):
        toujours_ko()
