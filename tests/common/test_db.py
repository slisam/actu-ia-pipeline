"""Tests de la base SQLite."""

from src.common.db import ajouter_article, article_existe, connexion


def test_ajout_et_doublon(tmp_path):
    chemin = tmp_path / "test.db"
    with connexion(chemin) as conn:
        assert ajouter_article(conn, "http://a.fr", "Titre", "Source") is True
        assert ajouter_article(conn, "http://a.fr", "Titre", "Source") is False
        assert article_existe(conn, "http://a.fr")
        assert not article_existe(conn, "http://b.fr")
