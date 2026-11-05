"""Mémoire durable des épisodes, indépendante des services externes."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class State:
    """Enregistre les scripts validés pour reprendre sans les régénérer."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, status TEXT NOT NULL, script_json TEXT, error TEXT, updated_at TEXT NOT NULL)")

    def connect(self) -> sqlite3.Connection:
        """Ouvre une connexion avec attente bornée du verrou SQLite."""
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def get(self, episode_id: str) -> dict | None:
        """Lit un épisode, ou renvoie None."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        return dict(row) if row else None

    def save(self, episode_id: str, status: str, script: dict | None = None, error: str | None = None) -> None:
        """Sauve atomiquement l'état, en conservant un script déjà validé."""
        payload = json.dumps(script, ensure_ascii=False) if script else None
        with self.connect() as db:
            db.execute("INSERT INTO episodes VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, script_json=COALESCE(excluded.script_json,episodes.script_json),error=excluded.error,updated_at=excluded.updated_at",
                       (episode_id, status, payload, error, datetime.now(timezone.utc).isoformat()))

    def used_urls(self, excluding: str | None = None) -> set[str]:
        """Évite de produire une nouvelle vidéo sur les mêmes articles."""
        with self.connect() as db:
            rows = db.execute("SELECT script_json FROM episodes WHERE script_json IS NOT NULL AND id != ?", (excluding or "",)).fetchall()
        return {source["url"] for row in rows if row[0] for source in json.loads(row[0]).get("sources", [])}

    def unfinished(self) -> list[str]:
        """Retrouve les publications interrompues, y compris les jours précédents."""
        with self.connect() as db:
            rows = db.execute("SELECT id FROM episodes WHERE status IN ('publication_incomplete','rendered','script_validated','failed') AND script_json IS NOT NULL ORDER BY id").fetchall()
        return [row[0] for row in rows]
