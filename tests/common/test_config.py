"""Tests du module de configuration."""

import pytest

from src.common import config
from src.common.config import ConfigError, charger_config, obtenir_cle


def test_charger_config_ok(tmp_path):
    f = tmp_path / "c.yaml"
    f.write_text("gemini:\n  text_model: test\n", encoding="utf-8")
    assert charger_config(f)["gemini"]["text_model"] == "test"


def test_charger_config_introuvable(tmp_path):
    with pytest.raises(ConfigError):
        charger_config(tmp_path / "absent.yaml")


def test_config_reelle_valide():
    data = charger_config()
    assert data["publish"]["privacy_status"] in ("private", "scheduled")
    assert len(data["collect"]["sources"]) > 0


def test_obtenir_cle_manquante(monkeypatch):
    monkeypatch.delenv("CLE_INEXISTANTE", raising=False)
    with pytest.raises(ConfigError):
        obtenir_cle("CLE_INEXISTANTE")


def test_obtenir_cle_presente(monkeypatch):
    monkeypatch.setenv("MA_CLE", "abc")
    assert obtenir_cle("MA_CLE") == "abc"


def test_dossier_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    d = config.dossier_episode("ep001")
    assert d.exists() and d.name == "ep001"
