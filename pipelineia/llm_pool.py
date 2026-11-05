"""Clés Gemini de secours, budgets persistants et arrêt global sur quota."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

PACIFIC = ZoneInfo("America/Los_Angeles")


class PoolError(RuntimeError):
    """Erreur sûre dont le message ne contient aucune réponse distante."""


class QuotaExhausted(PoolError):
    """Tous les appels de l'application attendent un renouvellement de quota."""


def _valid_slot(slot: dict, model: str) -> bool:
    """Contrôle des identifiants explicites, sans consultation de Google."""
    project = slot.get("quota_group", "")
    return (isinstance(slot, dict) and slot.get("provider", "gemini") == "gemini"
            and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(slot.get("id", ""))))
            and bool(re.fullmatch(r"[A-Z_][A-Z0-9_]{0,99}", str(slot.get("api_key_env", ""))))
            and isinstance(project, str) and bool(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project))
            and not project.startswith(("a-renseigner", "your-project", "example-project"))
            and bool(re.fullmatch(r"[A-Za-z0-9._-]{1,100}", str(slot.get("model", model)))))


def readiness(config: dict) -> dict[str, dict]:
    """Renvoie uniquement présence et validité locales ; ne vérifie pas la facturation."""
    settings = config.get("llm", {})
    slots = settings.get("api_pool", [])
    if not isinstance(slots, list):
        return {"configuration": {"ready": False, "status": "invalid_configuration"}}
    identifiers = Counter(slot.get("id") for slot in slots
                          if isinstance(slot, dict) and isinstance(slot.get("id"), str))
    result = {}
    for index, slot in enumerate(slots):
        if not isinstance(slot, dict):
            result[f"slot_{index + 1}"] = {"ready": False, "status": "invalid_configuration"}
            continue
        identifier = slot.get("id", "")
        safe_id = identifier if isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identifier) else f"slot_{index + 1}"
        valid = _valid_slot(slot, settings.get("model", "")) and identifiers[identifier] == 1
        confirmed = slot.get("free_tier_confirmed") is True
        present = valid and bool(os.environ.get(slot.get("api_key_env", ""), "").strip())
        result[safe_id] = {"ready": bool(valid and confirmed and present),
                           "configuration_valid": bool(valid), "free_tier_confirmed": confirmed,
                           "key_present": bool(present)}
    return result


def _day(now: float) -> str:
    """Date utilisée par le renouvellement quotidien officiel Gemini."""
    return datetime.fromtimestamp(now, PACIFIC).date().isoformat()


def _next_midnight(now: float) -> float:
    """Calcule minuit Pacific, y compris lors des changements saisonniers."""
    local = datetime.fromtimestamp(now, PACIFIC)
    tomorrow = local.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), PACIFIC).timestamp()


def _retry_at(response, payload: dict, now: float) -> float:
    """Respecte Retry-After, RetryInfo et le renouvellement quotidien si indiqué."""
    delays = [60.0]
    value = response.headers.get("Retry-After", "")
    try:
        delays.append(max(1.0, float(value)))
    except (ValueError, TypeError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            delays.append(max(1.0, stamp.timestamp() - now))
        except (ValueError, TypeError, OverflowError):
            pass
    data = json.dumps(payload, ensure_ascii=True).lower()
    for duration in re.findall(r'"retrydelay"\s*:\s*"(\d+(?:\.\d+)?)s"', data):
        delays.append(max(1.0, float(duration)))
    until = now + max(delays)
    if any(marker in data for marker in ("perday", "per_day", "requests/day", "dailyquota", "daily quota")):
        until = max(until, _next_midnight(now))
    return until


def _payload(response) -> dict:
    """Lit une réponse JSON sans transmettre son contenu à une exception."""
    try:
        value = response.json()
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _model_response(data: dict) -> dict:
    """Exige une réponse complète et un unique objet JSON, sans texte inventé."""
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ValueError("Gemini n'a pas fourni de réponse exploitable.")
    candidate = candidates[0]
    if candidate.get("finishReason") != "STOP":
        raise ValueError("Gemini a interrompu ou filtré la rédaction.")
    content = candidate.get("content", {})
    if not isinstance(content, dict) or not isinstance(content.get("parts", []), list):
        raise ValueError("Réponse Gemini malformée.")
    parts = content.get("parts", [])
    pieces = [item.get("text", "") for item in parts if isinstance(item, dict) and not item.get("thought")]
    if any(not isinstance(piece, str) for piece in pieces):
        raise ValueError("Réponse Gemini malformée.")
    text = "".join(pieces)
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("Réponse Gemini trop longue ou invalide.")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("Gemini n'a pas renvoyé le JSON attendu.") from None
    if not isinstance(value, dict):
        raise ValueError("Gemini doit renvoyer un objet JSON.")
    return value


class APIPool:
    """Réutilise les clés autorisées sans agréger les quotas de comptes Google."""

    def __init__(self, config: dict):
        self.settings = config.get("llm", {})
        self.requests = 0
        self.max_attempts = max(1, min(32, int(self.settings.get("max_http_attempts_per_run", 8))))
        self.daily_limit = max(1, min(1000, int(self.settings.get("daily_request_limit", 12))))
        self.path = Path(config.get("paths", {}).get("state_db", "data/state.sqlite3"))
        if not self.path.is_absolute():
            self.path = Path(config.get("project_root", ".")) / self.path
        report = readiness(config)
        self.slots = [dict(slot) for slot in self.settings.get("api_pool", [])
                      if isinstance(slot, dict) and report.get(slot.get("id"), {}).get("ready")]
        if not self.slots:
            raise PoolError("Aucune clé gratuite configurée : renseigner .env, quota_group et free_tier_confirmed dans config.yaml.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS llm_app_quota (id INTEGER PRIMARY KEY CHECK(id=1), blocked_until REAL NOT NULL DEFAULT 0)")
            db.execute("INSERT OR IGNORE INTO llm_app_quota(id) VALUES(1)")
            db.execute("CREATE TABLE IF NOT EXISTS llm_daily_usage (day TEXT NOT NULL, scope TEXT NOT NULL, attempts INTEGER NOT NULL, PRIMARY KEY(day,scope))")
            db.execute("CREATE TABLE IF NOT EXISTS llm_credentials (fingerprint TEXT PRIMARY KEY, disabled INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS llm_project_cooldown (project TEXT PRIMARY KEY, until_time REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        """Connexion locale avec attente limitée des verrous concurrents."""
        return sqlite3.connect(self.path, timeout=30)

    def _reserve(self, project: str, fingerprint: str) -> bool:
        """Réserve atomiquement une tentative ; les échecs consomment ce budget prudent."""
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            until = db.execute("SELECT blocked_until FROM llm_app_quota WHERE id=1").fetchone()[0]
            if until > now:
                raise QuotaExhausted("Quota Gemini en pause ; attendre le délai de reprise, sans changer de compte.")
            row = db.execute("SELECT attempts FROM llm_daily_usage WHERE day=? AND scope='application'", (_day(now),)).fetchone()
            if row and row[0] >= self.daily_limit:
                raise QuotaExhausted("Plafond quotidien partagé atteint ; reprendre après minuit Pacific.")
            disabled = db.execute("SELECT disabled FROM llm_credentials WHERE fingerprint=?", (fingerprint,)).fetchone()
            cooldown = db.execute("SELECT until_time FROM llm_project_cooldown WHERE project=?", (project,)).fetchone()
            if (disabled and disabled[0]) or (cooldown and cooldown[0] > now):
                return False
            for scope in ("application", "project:" + project):
                db.execute("INSERT INTO llm_daily_usage VALUES(?,?,1) ON CONFLICT(day,scope) DO UPDATE SET attempts=attempts+1", (_day(now), scope))
        return True

    def _disable(self, fingerprint: str) -> None:
        """Retient uniquement l'empreinte d'une clé refusée, jamais la clé."""
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO llm_credentials VALUES(?,1)", (fingerprint,))

    def _pause(self, until: float) -> None:
        """Une limite distante suspend toutes les clés de l'application."""
        with self._connect() as db:
            db.execute("UPDATE llm_app_quota SET blocked_until=MAX(blocked_until,?) WHERE id=1", (until,))

    def _cooldown(self, project: str) -> None:
        """Évite de répéter immédiatement un incident réseau sur le même projet."""
        with self._connect() as db:
            db.execute("INSERT INTO llm_project_cooldown VALUES(?,?) ON CONFLICT(project) DO UPDATE SET until_time=MAX(until_time,excluded.until_time)", (project, time.time() + 30))

    def generate(self, prompt: str) -> dict:
        """Effectue des tentatives bornées ; un HTTP429 arrête immédiatement le pool."""
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 120_000:
            raise ValueError("Prompt API absent ou trop long.")
        seen_keys = set()
        for slot in self.slots:
            key = os.environ.get(slot["api_key_env"], "").strip()
            if not key:
                continue
            fingerprint = hashlib.sha256(key.encode()).hexdigest()
            if fingerprint in seen_keys:
                continue
            seen_keys.add(fingerprint)
            if self.requests >= self.max_attempts:
                raise PoolError("Budget de tentatives HTTP de cet épisode atteint.")
            if not self._reserve(slot["quota_group"], fingerprint):
                continue
            self.requests += 1
            model = slot.get("model", self.settings.get("model", ""))
            try:
                response = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key},
                    json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          "generationConfig": {"responseMimeType": "application/json",
                                               "maxOutputTokens": max(128, min(8192, int(self.settings.get("max_output_tokens", 3000))))}},
                    timeout=max(1, min(180, int(self.settings.get("timeout_seconds", 60)))), allow_redirects=False)
            except requests.RequestException:
                self._cooldown(slot["quota_group"])
                continue
            data = _payload(response)
            if response.status_code == 429:
                self._pause(_retry_at(response, data, time.time()))
                raise QuotaExhausted("Quota Gemini atteint ; tous les comptes sont en pause jusqu'au délai de reprise.")
            if response.status_code in {401, 403} or (response.status_code == 400 and "API_KEY_INVALID" in json.dumps(data)):
                self._disable(fingerprint)
                continue
            if response.status_code in {500, 502, 503, 504}:
                self._cooldown(slot["quota_group"])
                continue
            if response.status_code != 200:
                raise PoolError(f"Gemini API a renvoyé HTTP {response.status_code} ; aucun changement de niveau payant.")
            return _model_response(data)
        raise PoolError("Aucune clé de secours disponible ; vérifier les clés autorisées ou attendre la reprise réseau.")
