"""Publication officielle avec journal durable et reprise sans doublon aveugle.

Les URL de sessions sont des secrets : conserver la base SQLite hors Git.
TikTok reste un export : ses règles Direct Post exigent une interface et un
consentement par publication, incompatibles avec ce traitement sans présence.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

LOG = logging.getLogger(__name__)
YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
TIKTOK_GUIDELINES = "https://developers.tiktok.com/docs/en/content-sharing-guidelines"


class PublishError(RuntimeError):
    """Erreur lisible sans corps HTTP ni secret dans le message."""


def _enabled(config: dict) -> list[str]:
    """Liste les destinations configurées, sans doublons."""
    value = config.get("publishing", {}).get("platforms", [])
    return list(dict.fromkeys(value))


def publishing_readiness(config: dict) -> dict[str, dict]:
    """Vérifie la configuration locale ; ne prétend pas valider les droits API."""
    requirements = {
        "youtube": ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"],
        "instagram": ["IG_USER_ID", "IG_ACCESS_TOKEN", "MEDIA_BASE_URL"],
    }
    result = {}
    for platform in _enabled(config):
        if platform == "tiktok":
            result[platform] = {"ready": False, "status": "export_only", "reason":
                "Export disponible ; Direct Post exige une interface et un consentement par post.",
                "documentation": TIKTOK_GUIDELINES}
        elif platform in requirements:
            missing = [name for name in requirements[platform] if not os.environ.get(name)]
            result[platform] = {"ready": not missing, "missing": missing,
                                "note": "Droits, validité OAuth et compte cible à vérifier côté plateforme."}
        else:
            result[platform] = {"ready": False, "reason": "Plateforme inconnue."}
    return result


class PublicationLedger:
    """Journal par épisode et plateforme, avec verrou temporaire interprocessus."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS publications (
            episode_id TEXT NOT NULL, platform TEXT NOT NULL, fingerprint TEXT NOT NULL,
            status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',
            remote_id TEXT, session_url TEXT, error TEXT, lease_until REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL, PRIMARY KEY (episode_id, platform))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS publisher_tokens (
            provider TEXT PRIMARY KEY, seed_hash TEXT NOT NULL,
            access_token TEXT NOT NULL, refreshed_at REAL NOT NULL)""")
        self.db.commit()

    def claim(self, episode_id: str, platform: str, fingerprint: str) -> dict | None:
        """Réserve une destination ou retourne None si elle est déjà traitée/en cours."""
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT * FROM publications WHERE episode_id=? AND platform=?",
                              (episode_id, platform)).fetchone()
        if row and row["fingerprint"] != fingerprint:
            self.db.rollback()
            raise PublishError("Cet épisode a déjà une autre vidéo ou d'autres métadonnées ; créer un nouvel identifiant.")
        if row and (row["status"] == "succeeded" or row["lease_until"] > now):
            self.db.commit()
            return None
        if row is None:
            self.db.execute("""INSERT INTO publications
                (episode_id,platform,fingerprint,status,lease_until,updated_at) VALUES (?,?,?,'pending',?,?)""",
                (episode_id, platform, fingerprint, now + 900, now))
        else:
            self.db.execute("UPDATE publications SET lease_until=?,updated_at=? WHERE episode_id=? AND platform=?",
                            (now + 900, now, episode_id, platform))
        self.db.commit()
        return self.get(episode_id, platform)

    def get(self, episode_id: str, platform: str) -> dict:
        """Lit l'état durable d'une destination."""
        row = self.db.execute("SELECT * FROM publications WHERE episode_id=? AND platform=?",
                              (episode_id, platform)).fetchone()
        return dict(row) if row else {}

    def save(self, episode_id: str, platform: str, **values: Any) -> None:
        """Enregistre une transition avant l'appel distant susceptible de publier."""
        allowed = {"status", "stage", "remote_id", "session_url", "error", "lease_until"}
        if not set(values) <= allowed:
            raise ValueError("Colonne de journal inconnue.")
        values["updated_at"] = time.time()
        assignment = ",".join(f"{key}=?" for key in values)
        self.db.execute(f"UPDATE publications SET {assignment} WHERE episode_id=? AND platform=?",
                        (*values.values(), episode_id, platform))
        self.db.commit()

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        self.db.close()


def _check(response: requests.Response, operation: str) -> dict:
    """Ne laisse jamais fuiter URL signée, token ou corps d'erreur distant."""
    if not 200 <= response.status_code < 300:
        raise PublishError(f"{operation} : HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError:
        raise PublishError(f"{operation} : réponse JSON invalide.") from None
    if not isinstance(payload, dict) or payload.get("error"):
        raise PublishError(f"{operation} : erreur API (consulter la console de la plateforme).")
    return payload


def _youtube_session() -> requests.Session:
    """Renouvelle le jeton YouTube avec les identifiants OAuth du propriétaire."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    credentials = Credentials(
        token=None, refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"], client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    try:
        credentials.refresh(Request())
    except Exception:
        raise PublishError("YouTube : renouvellement OAuth impossible ; vérifier l'autorisation initiale.") from None
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {credentials.token}"
    return session


def _safe_youtube_url(value: str) -> bool:
    """Évite l'envoi du jeton OAuth vers une URL de session étrangère."""
    url = urlparse(value)
    return url.scheme == "https" and url.hostname in {"www.googleapis.com", "youtube.googleapis.com"}


def _youtube(episode_id: str, manifest: dict, video: Path, config: dict,
             ledger: PublicationLedger, row: dict) -> None:
    """Charge ou reprend une seule session YouTube existante."""
    options = config.get("publishing", {}).get("youtube", {})
    privacy = options.get("privacy", "private")
    if privacy not in {"private", "unlisted", "public"}:
        raise PublishError("YouTube : privacy doit être private, unlisted ou public.")
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(options.get("synthetic_media", True))}
    if options.get("publish_at"):
        if privacy != "private":
            raise PublishError("YouTube : une date publish_at exige privacy: private.")
        status["publishAt"] = options["publish_at"]
    body = {"snippet": {"title": manifest["title"][:100],
                        "description": manifest.get("description", "")[:5000],
                        "categoryId": str(options.get("category_id", "28")),
                        "defaultLanguage": "fr"}, "status": status}
    session = _youtube_session()
    size = video.stat().st_size
    session_url = row.get("session_url")
    offset = 0
    if session_url:
        if not _safe_youtube_url(session_url):
            raise PublishError("YouTube : URL de session non autorisée dans le journal.")
        # Le serveur indique si le PUT précédent a terminé malgré une réponse perdue.
        response = session.put(session_url, headers={"Content-Length": "0", "Content-Range": f"bytes */{size}"},
                               data=b"", timeout=60, allow_redirects=False)
        if response.status_code in {200, 201}:
            data = _check(response, "YouTube statut")
            if not data.get("id"):
                raise PublishError("YouTube : vidéo sans identifiant dans la réponse.")
            ledger.save(episode_id, "youtube", status="succeeded", stage="complete", remote_id=data["id"], error=None)
            return
        if response.status_code != 308:
            raise PublishError("YouTube : état de la session inconnu ou expiré ; vérifier la chaîne avant toute nouvelle session.")
        server_range = response.headers.get("Range", "")
        if server_range:
            match = re.fullmatch(r"bytes=0-(\d+)", server_range)
            if not match:
                raise PublishError("YouTube : plage reçue invalide.")
            offset = int(match.group(1)) + 1
    else:
        ledger.save(episode_id, "youtube", status="uploading", stage="initializing", error=None)
        response = session.post(YT_UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"},
                                json=body, headers={"X-Upload-Content-Length": str(size),
                                                   "X-Upload-Content-Type": "video/mp4"}, timeout=60)
        if not 200 <= response.status_code < 300:
            raise PublishError(f"YouTube initialisation : HTTP {response.status_code}.")
        session_url = response.headers.get("Location", "")
        if not _safe_youtube_url(session_url):
            raise PublishError("YouTube : réponse sans URL de session autorisée.")
        ledger.save(episode_id, "youtube", status="uploading", stage="upload", session_url=session_url)
    if offset >= size:
        raise PublishError("YouTube : tous les octets sont reçus mais la finalisation reste inconnue.")
    headers = {"Content-Type": "video/mp4", "Content-Length": str(size - offset),
               "Content-Range": f"bytes {offset}-{size - 1}/{size}"}
    with video.open("rb") as stream:
        stream.seek(offset)
        response = session.put(session_url, headers=headers, data=stream, timeout=180, allow_redirects=False)
    if response.status_code == 308:
        ledger.save(episode_id, "youtube", status="pending", stage="upload")
        return
    data = _check(response, "YouTube chargement")
    if not data.get("id"):
        raise PublishError("YouTube : réponse sans identifiant ; la session sera interrogée à la reprise.")
    ledger.save(episode_id, "youtube", status="succeeded", stage="complete", remote_id=data["id"], error=None)


def _public_media(episode_id: str, video: Path) -> str:
    """Copie optionnellement le MP4 vers un répertoire déjà servi en HTTPS."""
    base_url = os.environ["MEDIA_BASE_URL"].rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise PublishError("Instagram : MEDIA_BASE_URL doit être une base HTTPS publique sans identifiants ni paramètres.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", episode_id):
        raise PublishError("Identifiant d'épisode invalide pour l'hébergement public.")
    upload_dir = os.environ.get("MEDIA_UPLOAD_DIR")
    bucket = os.environ.get("MEDIA_S3_BUCKET")
    if bucket:
        try:
            import boto3
            endpoint = os.environ.get("MEDIA_S3_ENDPOINT")
            if endpoint and urlparse(endpoint).scheme != "https":
                raise PublishError("L'hébergement S3 doit utiliser HTTPS.")
            client = boto3.client("s3", endpoint_url=endpoint,
                                  region_name=os.environ.get("AWS_DEFAULT_REGION", "auto"))
            client.upload_file(str(video), bucket, f"{episode_id}/vertical.mp4",
                               ExtraArgs={"ContentType": "video/mp4", "CacheControl": "public, max-age=86400"})
        except PublishError:
            raise
        except Exception:
            raise PublishError("Instagram : transfert S3/R2 impossible ; vérifier le bucket et les identifiants.") from None
    if upload_dir:
        target = Path(upload_dir).resolve() / episode_id / "vertical.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() != video.resolve():
            shutil.copy2(video, target)
    return f"{base_url}/{quote(episode_id, safe='')}/vertical.mp4"


def _instagram(episode_id: str, manifest: dict, video: Path, config: dict,
               ledger: PublicationLedger, row: dict) -> None:
    """Publie un Reel via un conteneur conservé dans SQLite avant publication."""
    options = config.get("publishing", {}).get("instagram", {})
    version = options.get("api_version", "v25.0")
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise PublishError("Instagram : version API invalide.")
    login = options.get("login", "instagram")
    if login not in {"instagram", "facebook"}:
        raise PublishError("Instagram : login doit être instagram ou facebook.")
    host = "graph.instagram.com" if login == "instagram" else "graph.facebook.com"
    base = f"https://{host}/{version}"
    user_id = os.environ["IG_USER_ID"]
    if not re.fullmatch(r"\d+", user_id):
        raise PublishError("Instagram : IG_USER_ID doit être numérique.")
    session = requests.Session()
    token = os.environ["IG_ACCESS_TOKEN"]
    if login == "instagram" and options.get("refresh_long_lived_token", True):
        token = _instagram_token(token, ledger)
    session.headers["Authorization"] = f"Bearer {token}"
    container = row.get("remote_id")
    if not container:
        media_url = _public_media(episode_id, video)
        # Vérifie seulement l'accessibilité ; Meta télécharge ensuite depuis son réseau.
        probe = requests.head(media_url, timeout=30, allow_redirects=True)
        if not 200 <= probe.status_code < 300:
            raise PublishError(f"Instagram : MP4 public inaccessible (HTTP {probe.status_code}).")
        ledger.save(episode_id, "instagram", status="uploading", stage="creating", error=None)
        response = session.post(f"{base}/{user_id}/media", data={
            "media_type": "REELS", "video_url": media_url,
            "caption": (manifest["title"] + "\n\n" + manifest.get("description", ""))[:2200],
            "share_to_feed": "true"}, timeout=60)
        data = _check(response, "Instagram conteneur")
        container = data.get("id")
        if not container or not re.fullmatch(r"\d+", str(container)):
            raise PublishError("Instagram : réponse sans identifiant de conteneur.")
        ledger.save(episode_id, "instagram", status="pending", stage="processing", remote_id=container)
    publish_was_sent = row.get("stage") == "publish_sent"
    for attempt in range(int(options.get("poll_attempts", 6))):
        response = session.get(f"{base}/{container}", params={"fields": "status_code,status"}, timeout=30)
        data = _check(response, "Instagram statut")
        status = data.get("status_code")
        if status == "PUBLISHED":
            ledger.save(episode_id, "instagram", status="succeeded", stage="complete", error=None)
            return
        if publish_was_sent:
            raise PublishError("Instagram : publication précédente ambiguë ; vérifier le profil, aucun nouvel envoi automatique.")
        if status == "FINISHED":
            # Le journal précède le POST, donc un arrêt brutal ne peut causer un deuxième envoi.
            ledger.save(episode_id, "instagram", status="uploading", stage="publish_sent")
            response = session.post(f"{base}/{user_id}/media_publish", data={"creation_id": container}, timeout=60)
            data = _check(response, "Instagram publication")
            if not data.get("id"):
                raise PublishError("Instagram : réponse sans identifiant de publication.")
            ledger.save(episode_id, "instagram", status="succeeded", stage="complete", remote_id=data["id"], error=None)
            return
        if status in {"ERROR", "EXPIRED"}:
            raise PublishError("Instagram : conteneur en erreur ou expiré ; vérifier dans Meta avant réinitialisation du journal.")
        if attempt + 1 < int(options.get("poll_attempts", 6)):
            time.sleep(min(float(options.get("poll_interval", 5)), 10))
    ledger.save(episode_id, "instagram", status="pending", stage="processing", error=None)


def _instagram_token(seed: str, ledger: PublicationLedger) -> str:
    """Renouvelle chaque semaine un jeton Instagram Login de longue durée.

    Le jeton d'environnement amorce le cache. Sa modification réinitialise ce
    cache. La base contenant les jetons doit être conservée sous chiffrement.
    Un jeton initial de moins de 24 h reste utilisé, puis est réessayé demain.
    """
    seed_hash = hashlib.sha256(seed.encode()).hexdigest()
    row = ledger.db.execute("SELECT * FROM publisher_tokens WHERE provider='instagram'").fetchone()
    now = time.time()
    if row and row["seed_hash"] == seed_hash:
        token = row["access_token"]
        if now - row["refreshed_at"] < 7 * 86400:
            return token
    else:
        token = seed
    response = requests.get("https://graph.instagram.com/refresh_access_token",
                            params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    if response.status_code == 400:
        # Un jeton tout neuf ne peut pas être renouvelé. L'appel de publication
        # vérifie ensuite ses droits ; une expiration ne peut donc passer inaperçue.
        next_refresh_base = now - 6 * 86400
        refreshed = token
    else:
        data = _check(response, "Instagram renouvellement OAuth")
        refreshed = data.get("access_token")
        if not isinstance(refreshed, str) or not refreshed:
            raise PublishError("Instagram : renouvellement sans jeton, vérifier l'autorisation.")
        next_refresh_base = now
    ledger.db.execute("""INSERT INTO publisher_tokens(provider,seed_hash,access_token,refreshed_at)
        VALUES('instagram',?,?,?) ON CONFLICT(provider) DO UPDATE SET
        seed_hash=excluded.seed_hash,access_token=excluded.access_token,refreshed_at=excluded.refreshed_at""",
        (seed_hash, refreshed, next_refresh_base))
    ledger.db.commit()
    return refreshed


def _summary(row: dict) -> dict:
    """Expose uniquement les informations non secrètes du journal."""
    return {key: row.get(key) for key in ("status", "stage", "remote_id", "error")}


def publish_episode(episode_dir: Path, config: dict, state: Any = None) -> dict:
    """Publie les destinations prêtes indépendamment et conserve toutes les reprises.

    ``state`` est réservé à l'intégration ; le journal de publication reste autonome.
    Une erreur d'une plateforme n'annule jamais la réussite d'une autre.
    """
    episode_dir = Path(episode_dir)
    manifest = json.loads((episode_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("demo"):
        raise PublishError("Une vidéo de démonstration ne peut jamais être publiée.")
    episode_id = manifest["episode_id"]
    videos = manifest.get("videos", {})
    video_value = videos.get("vertical")
    if not video_value:
        raise PublishError("Le manifeste ne contient pas de vidéo verticale.")
    video = Path(video_value)
    if not video.is_absolute():
        # Les manifestes portables contiennent un nom relatif à leur propre dossier.
        video = episode_dir / video
    if not video.is_file():
        raise PublishError("Le fichier MP4 du manifeste est introuvable.")
    digest = hashlib.sha256()
    with video.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    digest.update(json.dumps({key: manifest.get(key) for key in ("title", "description", "sources")},
                             sort_keys=True, ensure_ascii=False).encode("utf-8"))
    ledger = PublicationLedger(Path(config.get("paths", {}).get("state_db", "data/state.sqlite3")))
    readiness = publishing_readiness(config)
    results = {}
    try:
        for platform in _enabled(config):
            if platform == "tiktok":
                package = {"video": str(video.resolve()), "title": manifest["title"],
                           "caption": manifest.get("description", ""), "status": "export_only",
                           "documentation": TIKTOK_GUIDELINES}
                (episode_dir / "tiktok-export.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
                results[platform] = readiness[platform]
                continue
            if not readiness[platform]["ready"]:
                results[platform] = {"status": "not_configured", **readiness[platform]}
                continue
            fingerprint = hashlib.sha256((digest.hexdigest() + json.dumps(
                config.get("publishing", {}).get(platform, {}), sort_keys=True)).encode()).hexdigest()
            try:
                row = ledger.claim(episode_id, platform, fingerprint)
            except PublishError as exc:
                results[platform] = {"status": "conflict", "error": str(exc)}
                continue
            if row is None:
                results[platform] = _summary(ledger.get(episode_id, platform))
                continue
            try:
                if platform == "youtube":
                    _youtube(episode_id, manifest, video, config, ledger, row)
                elif platform == "instagram":
                    _instagram(episode_id, manifest, video, config, ledger, row)
            except Exception as exc:
                current = ledger.get(episode_id, platform)
                if current:
                    ambiguous = (current.get("stage") in {"upload", "publish_sent"})
                    message = str(exc) if isinstance(exc, PublishError) else "Erreur réseau ou interne ; reprise conservée dans le journal."
                    ledger.save(episode_id, platform, status="uncertain" if ambiguous else "failed", error=message)
                else:
                    results[platform] = {"status": "failed", "error": str(exc) if isinstance(exc, PublishError) else "Journal indisponible."}
                LOG.warning("Publication %s : échec, consulter publication.json.", platform)
            finally:
                if ledger.get(episode_id, platform):
                    ledger.save(episode_id, platform, lease_until=0)
            if platform not in results:
                results[platform] = _summary(ledger.get(episode_id, platform))
    finally:
        ledger.close()
    (episode_dir / "publication.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results
