"""Accès à la base SQLite (data/pipeline.db)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

RACINE = Path(__file__).resolve().parents[2]
DB_PATH = RACINE / "data" / "pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    titre TEXT NOT NULL,
    source TEXT NOT NULL,
    resume TEXT,
    date_publication TEXT,
    date_collecte TEXT NOT NULL DEFAULT (datetime('now')),
    utilise INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    statut TEXT NOT NULL DEFAULT 'cree',
    date_creation TEXT NOT NULL DEFAULT (datetime('now')),
    youtube_id TEXT
);
"""


@contextmanager
def connexion(chemin: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Ouvre une connexion SQLite, crée les tables si besoin, puis la ferme.

    Les changements sont validés (commit) à la sortie, ou annulés en cas d'erreur.
    """
    chemin = chemin or DB_PATH
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chemin)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def article_existe(conn: sqlite3.Connection, url: str) -> bool:
    """Indique si un article (identifié par son URL) est déjà en base."""
    ligne = conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
    return ligne is not None


def ajouter_article(conn: sqlite3.Connection, url: str, titre: str, source: str,
                    resume: str = "", date_publication: str = "") -> bool:
    """Ajoute un article. Retourne False s'il existait déjà (doublon d'URL)."""
    if article_existe(conn, url):
        return False
    conn.execute(
        "INSERT INTO articles (url, titre, source, resume, date_publication) "
        "VALUES (?, ?, ?, ?, ?)",
        (url, titre, source, resume, date_publication),
    )
    return True
