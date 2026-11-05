"""Alertes Telegram privées, journal durable et déduplication des incidents."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import requests

LOGGER = logging.getLogger(__name__)
STAGES = {"startup": "Démarrage", "collect": "Collecte des sources", "write": "Rédaction Gemini",
          "voice": "Voix off", "render": "Montage vidéo", "publish": "Publication"}
CODES = {
    "unexpected": ("Incident inattendu", "Consulter les journaux locaux avant de relancer."),
    "quota": ("Quota ou crédits indisponibles", "Vérifier les crédits et quotas du service, puis attendre leur renouvellement ou corriger la configuration."),
    "credentials": ("Connexion ou autorisation refusée", "Vérifier les clés, autorisations et le compte du service concerné."),
    "uncertain": ("Résultat distant incertain", "Vérifier l'historique du service ou la publication avant tout nouvel envoi."),
    "configuration": ("Configuration incomplète ou invalide", "Compléter les réglages locaux puis lancer le diagnostic doctor."),
    "failed": ("Traitement interrompu", "Consulter les journaux locaux de l'épisode avant de relancer."),
    "pending": ("Traitement distant toujours en attente", "Vérifier l'état sur la plateforme ; la reprise conserve le journal d'envoi."),
    "conflict": ("Conflit avec un envoi déjà enregistré", "Vérifier la publication existante et les fichiers ; ne pas effacer le journal pour réenvoyer."),
    "test": ("Test des alertes", "La connexion aux alertes fonctionne."),
}
PLATFORMS = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"}


def _settings(config: dict) -> dict:
    """Borne la consommation du canal de notification."""
    value = config.get("alerts", {})
    if not isinstance(value, dict):
        raise ValueError("Configuration des alertes invalide.")
    result = {"enabled": value.get("enabled", False) is True, "provider": value.get("provider", "telegram")}
    for key, default, low, high in (("cooldown_seconds", 3600, 60, 604800),
                                   ("max_attempts", 3, 1, 10), ("retry_base_seconds", 60, 1, 86400),
                                   ("timeout_seconds", 10, 1, 30), ("batch_size", 10, 1, 50),
                                   ("pending_delay_seconds", 900, 0, 86400)):
        raw = value.get(key, default)
        if isinstance(raw, bool):
            raise ValueError("Réglage des alertes invalide.")
        result[key] = max(low, min(high, int(raw)))
    return result


def alert_readiness(config: dict) -> dict:
    """Vérifie seulement les réglages et secrets présents, sans réseau ni journal."""
    try:
        settings = _settings(config)
        token_ok = bool(re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,200}", os.getenv("TELEGRAM_BOT_TOKEN", "").strip()))
        chat_ok = bool(re.fullmatch(r"[1-9][0-9]{0,19}", os.getenv("TELEGRAM_CHAT_ID", "").strip()))
        return {"enabled": settings["enabled"], "provider": "telegram",
                "ready": settings["enabled"] and settings["provider"] == "telegram" and token_ok and chat_ok,
                "token_present": token_ok, "private_chat_configured": chat_ok,
                "provider_valid": settings["provider"] == "telegram",
                "missing": (["TELEGRAM_BOT_TOKEN"] if not token_ok else []) + (["TELEGRAM_CHAT_ID"] if not chat_ok else [])}
    except Exception:
        return {"enabled": False, "ready": False, "status": "invalid_configuration"}


def _path(config: dict) -> Path:
    """Utilise la base privée existante du pipeline."""
    path = Path(config.get("paths", {}).get("state_db", "data/state.sqlite3"))
    return path if path.is_absolute() else Path(config.get("project_root", ".")) / path


@contextmanager
def _db(config: dict):
    """Crée le journal isolément, puis ferme sa connexion même après une erreur."""
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            episode_id TEXT NOT NULL, stage TEXT NOT NULL, code TEXT NOT NULL, platform TEXT,
            message TEXT NOT NULL, status TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0,
            occurrences INTEGER NOT NULL DEFAULT 1, attempts INTEGER NOT NULL DEFAULT 0,
            first_seen REAL NOT NULL, last_seen REAL NOT NULL, last_sent REAL,
            next_attempt REAL NOT NULL, lease_until REAL NOT NULL DEFAULT 0, claim TEXT,
            delivery_error TEXT, delivery_route_hash TEXT)""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(alerts)")}
        if "delivery_route_hash" not in columns:
            db.execute("ALTER TABLE alerts ADD COLUMN delivery_route_hash TEXT")
        db.commit()
        yield db
    finally:
        db.close()


def _event(episode_id: str, stage: str, code: str, platform: str | None) -> tuple[str, str, str, str | None, str, str]:
    """N'accepte que des identifiants bornés et des messages prédéfinis."""
    episode = episode_id if isinstance(episode_id, str) and re.fullmatch(r"(?:\d{4}-\d{2}-\d{2}-actu-ia|pipeline|test)", episode_id) else "pipeline"
    step = stage if isinstance(stage, str) and stage in STAGES else "startup"
    reason = code if isinstance(code, str) and code in CODES else "unexpected"
    destination = platform if isinstance(platform, str) and platform in PLATFORMS else None
    title, action = CODES[reason]
    message = f"Pipelineia — {title}\nÉpisode : {episode}\nÉtape : {STAGES[step]}"
    if destination:
        message += f"\nPlateforme : {PLATFORMS[destination]}"
    message += f"\nAction : {action}"
    fingerprint = hashlib.sha256("\0".join((episode, step, reason, destination or "")).encode()).hexdigest()
    return episode, step, reason, destination, message, fingerprint


def _route_hash(config: dict) -> str | None:
    """Détecte une connexion corrigée sans enregistrer ses identifiants."""
    if not alert_readiness(config).get("ready"):
        return None
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    return hashlib.sha256((token + "\0" + chat).encode()).hexdigest()


def _record(config: dict, settings: dict, event: tuple) -> int:
    """Regroupe les répétitions d'un incident sans repousser l'alerte initiale."""
    episode, stage, code, platform, message, fingerprint = event
    now = time.time()
    route = _route_hash(config)
    with _db(config) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM alerts WHERE fingerprint=?", (fingerprint,)).fetchone()
        if row is None:
            due = now + (settings["pending_delay_seconds"] if code == "pending" else 0)
            cursor = db.execute("""INSERT INTO alerts
                (fingerprint,episode_id,stage,code,platform,message,status,first_seen,last_seen,next_attempt)
                VALUES(?,?,?,?,?,?,'pending',?,?,?)""", (fingerprint, episode, stage, code, platform, message, now, now, due))
            identifier = cursor.lastrowid
        else:
            identifier = row["id"]
            corrected_route = row["status"] == "failed" and route is not None and row["delivery_route_hash"] is not None and route != row["delivery_route_hash"]
            new_incident = bool(row["resolved"]) or corrected_route or (row["status"] == "sent" and now - (row["last_sent"] or row["first_seen"]) >= settings["cooldown_seconds"])
            if new_incident:
                due = now + (settings["pending_delay_seconds"] if code == "pending" else 0)
                db.execute("""UPDATE alerts SET status='pending',resolved=0,attempts=0,
                    first_seen=?,last_seen=?,last_sent=NULL,next_attempt=?,lease_until=0,claim=NULL,
                    delivery_error=NULL,occurrences=occurrences+1 WHERE id=?""", (now, now, due, identifier))
            else:
                db.execute("UPDATE alerts SET last_seen=?,occurrences=occurrences+1 WHERE id=?", (now, identifier))
        db.commit()
        return identifier


def _claim(config: dict, settings: dict, identifier: int | None = None) -> dict | None:
    """Réserve l'envoi avant le réseau et rend ambigu tout ancien envoi interrompu."""
    now = time.time()
    with _db(config) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE alerts SET status='uncertain',claim=NULL,lease_until=0,delivery_error='interrupted' WHERE status='sending' AND lease_until<=? AND resolved=0", (now,))
        query = "SELECT * FROM alerts WHERE status='pending' AND resolved=0 AND next_attempt<=? AND attempts<?"
        params = [now, settings["max_attempts"]]
        if identifier is not None:
            query += " AND id=?"
            params.append(identifier)
        row = db.execute(query + " ORDER BY first_seen,id LIMIT 1", params).fetchone()
        if row is None:
            db.commit()
            return None
        claim = uuid.uuid4().hex
        db.execute("UPDATE alerts SET status='sending',attempts=attempts+1,lease_until=?,claim=?,delivery_route_hash=? WHERE id=?", (now + settings["timeout_seconds"] + 30, claim, _route_hash(config), row["id"]))
        db.commit()
        result = dict(row)
        result.update(claim=claim, attempts=row["attempts"] + 1)
        return result


def _finish(config: dict, row: dict, status: str, error: str | None = None, retry: float = 0) -> None:
    """Enregistre seulement un code de livraison local, jamais le corps distant."""
    now = time.time()
    with _db(config) as db:
        db.execute("""UPDATE alerts SET status=?,delivery_error=?,next_attempt=?,lease_until=0,claim=NULL,
            last_sent=CASE WHEN ?='sent' THEN ? ELSE last_sent END
            WHERE id=? AND claim=?""", (status, error, now + retry, status, now, row["id"], row["claim"]))
        db.commit()


def _deliver(config: dict, settings: dict, row: dict) -> str:
    """Effectue un seul POST ; une livraison possible mais non confirmée ne se répète pas."""
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                 json={"chat_id": chat, "text": row["message"],
                                       "protect_content": True, "disable_web_page_preview": True,
                                       "allow_paid_broadcast": False},
                                 timeout=settings["timeout_seconds"], allow_redirects=False)
    except Exception:
        _finish(config, row, "uncertain", "network_uncertain")
        return "uncertain"
    try:
        body = response.json()
    except (ValueError, TypeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    if response.status_code == 200 and body.get("ok") is True:
        _finish(config, row, "sent")
        return "sent"
    error_code = body.get("error_code")
    if response.status_code == 429 or error_code == 429:
        retry = body.get("parameters", {})
        try:
            delay = max(1, min(604800, int(retry.get("retry_after", settings["retry_base_seconds"]))))
        except (AttributeError, TypeError, ValueError, OverflowError):
            delay = settings["retry_base_seconds"]
        status = "failed" if row["attempts"] >= settings["max_attempts"] else "pending"
        _finish(config, row, status, "rate_limited", delay)
        return status
    if 400 <= response.status_code < 500 or (response.status_code == 200 and body.get("ok") is False):
        _finish(config, row, "failed", "rejected")
        return "failed"
    # Une réponse serveur ou JSON illisible peut suivre un envoi effectué.
    _finish(config, row, "uncertain", "response_uncertain")
    return "uncertain"


def _queue_counts(config: dict) -> dict:
    """Compte les incidents non résolus, sans inclure l'historique livré."""
    counts = {"pending": 0, "failed": 0, "uncertain": 0}
    with _db(config) as db:
        for status, count in db.execute("SELECT status,COUNT(*) FROM alerts WHERE resolved=0 GROUP BY status"):
            if status in counts:
                counts[status] = count
            elif status == "sending":
                counts["pending"] += count
    return counts


def _flush(config: dict, settings: dict, identifier: int | None = None) -> dict:
    """Ne prend aucun verrou SQLite pendant une requête réseau."""
    if not alert_readiness(config).get("ready"):
        return {"status": "not_configured", "sent": 0, **_queue_counts(config)}
    counts = {"status": "complete", "sent": 0, "pending": 0, "failed": 0, "uncertain": 0}
    for _ in range(1 if identifier is not None else settings["batch_size"]):
        row = _claim(config, settings, identifier)
        if row is None:
            break
        counts[_deliver(config, settings, row)] += 1
    return {**counts, **_queue_counts(config)}


def notify_failure(config: dict, episode_id: str, stage: str, code: str = "unexpected", platform: str | None = None) -> dict:
    """Journalise et tente une alerte sûre ; une panne du canal ne se propage jamais."""
    try:
        settings = _settings(config)
        if not settings["enabled"]:
            return {"status": "disabled"}
        identifier = _record(config, settings, _event(episode_id, stage, code, platform))
        delivery = _flush(config, settings, identifier)
        with _db(config) as db:
            row = db.execute("SELECT status,occurrences,resolved FROM alerts WHERE id=?", (identifier,)).fetchone()
        return {"status": row["status"], "occurrences": row["occurrences"], "delivery": delivery["status"]}
    except Exception:
        LOGGER.warning("Alerte non disponible ; l'incident du pipeline reste prioritaire.")
        return {"status": "unavailable"}


def resolve_episode(config: dict, episode_id: str) -> None:
    """Annule les anciennes alertes de l'épisode après une reprise réussie."""
    try:
        if not _settings(config)["enabled"]:
            return
        episode = _event(episode_id, "startup", "unexpected", None)[0]
        with _db(config) as db:
            db.execute("UPDATE alerts SET resolved=1 WHERE episode_id=?", (episode,))
            db.commit()
    except Exception:
        LOGGER.warning("Résolution d'alerte indisponible ; le résultat du pipeline est conservé.")


def flush_alerts(config: dict) -> dict:
    """Traite la file éligible sans jamais masquer le résultat du traitement principal."""
    try:
        settings = _settings(config)
        if not settings["enabled"]:
            return {"status": "disabled", "sent": 0}
        return _flush(config, settings)
    except Exception:
        LOGGER.warning("Envoi des alertes indisponible ; le résultat du pipeline est conservé.")
        return {"status": "unavailable", "sent": 0}
