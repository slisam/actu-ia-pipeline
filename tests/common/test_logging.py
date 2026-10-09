"""Tests de la configuration du logging."""

from src.common.logging_setup import configurer_logging


def test_logging_cree_fichier(tmp_path):
    logger = configurer_logging("test_mod", dossier_logs=tmp_path)
    logger.info("bonjour")
    assert any(tmp_path.glob("test_mod_*.log"))
