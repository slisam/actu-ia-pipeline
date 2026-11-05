"""Orchestration quotidienne et reprise des épisodes interrompus."""
import copy
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from filelock import FileLock

from . import __version__
from .demo import demo_script
from .news import collect_news
from .publish import publish_episode
from .render import render_episode
from .speech import synthesize
from .state import State
from .writer import write_script

LOGGER = logging.getLogger(__name__)


def write_json(path: Path, payload: dict | list) -> None:
    """Remplace un JSON atomiquement, même après un arrêt précédent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    """Calcule une empreinte sans charger le MP4 en mémoire."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_episode(config: dict, publish: bool = False, demo: bool = False,
                quick: bool = False, silent: bool = False, episode_id: str | None = None) -> dict:
    """Produit au plus un épisode réel par jour, sous un verrou partagé."""
    config = copy.deepcopy(config)
    if silent and not demo:
        raise ValueError("La voix silencieuse est réservée aux démonstrations.")
    if not demo and config.get("speech", {}).get("provider") == "demo":
        raise ValueError("speech.provider=demo est réservé aux démonstrations.")
    if demo and publish:
        raise ValueError("Une démonstration ne peut pas être publiée.")
    if quick and not demo:
        raise ValueError("La basse résolution rapide est réservée aux démonstrations.")
    if publish and not config.get("publishing", {}).get("platforms"):
        raise ValueError("Aucune destination de publication configurée dans publishing.platforms.")
    if episode_id and not re.fullmatch(r"\d{4}-\d{2}-\d{2}-actu-ia", episode_id):
        raise ValueError("Identifiant d'épisode invalide.")
    state_path = Path(config["paths"]["state_db"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(state_path) + ".lock", timeout=0):
        date = datetime.now(ZoneInfo(config.get("timezone", "Europe/Paris"))).date().isoformat()
        episode_id = "demo" if demo else (episode_id or date + "-actu-ia")
        directory = Path(config["paths"]["output"]) / episode_id
        directory.mkdir(parents=True, exist_ok=True)
        state = State(state_path)
        row = state.get(episode_id) if not demo else None
        try:
            if demo:
                script = demo_script()
            elif row and row["script_json"]:
                script = json.loads(row["script_json"])
                LOGGER.info("Reprise du script validé : %s", episode_id)
            else:
                articles = collect_news(config, used_urls=state.used_urls(excluding=episode_id))
                write_json(directory / "articles.json", articles)
                if not articles:
                    LOGGER.warning("Aucune actualité récente exploitable ; aucune vidéo fabriquée.")
                    return {"status": "no_news", "episode_id": episode_id}
                script = write_script(articles, config)
                state.save(episode_id, "script_validated", script)
            if publish:
                now = datetime.now(ZoneInfo(config.get("timezone", "Europe/Paris")))
                dates = [datetime.fromisoformat(source["published_at"]) for source in script.get("sources", []) if source.get("published_at")]
                if not dates:
                    dates = [datetime.fromisoformat(episode_id[:10]).replace(tzinfo=now.tzinfo)]
                if any((now - date.replace(tzinfo=date.tzinfo or now.tzinfo)).total_seconds() > float(config.get("news", {}).get("max_age_hours", 48)) * 3600 for date in dates):
                    state.save(episode_id, "expired", script)
                    LOGGER.warning("Épisode périmé, publication ignorée : %s", episode_id)
                    return {"status": "expired", "episode_id": episode_id}
            write_json(directory / "script.json", script)
            narration = " ".join(scene["narration"] for scene in script["scenes"])
            (directory / "narration.txt").write_text(narration, encoding="utf-8")
            if quick:
                config["video"]["formats"] = {"vertical": {"width": 270, "height": 480}}
                config["video"]["fps"] = 15
            if silent:
                config["speech"]["provider"] = "demo"
            # Les empreintes couvrent le script et les paramètres du rendu.
            speech_signature = dict(config["speech"])
            if speech_signature.get("provider") == "elevenlabs":
                speech_signature["effective_voice_id"] = speech_signature.get("elevenlabs", {}).get("voice_id") or os.getenv("ELEVENLABS_VOICE_ID", "")
            signature = hashlib.sha256(json.dumps({"pipeline_version": __version__, "script": script, "video": config["video"], "speech": speech_signature}, sort_keys=True).encode()).hexdigest()
            manifest_path = directory / "manifest.json"
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
            except (ValueError, OSError):
                previous = {}
            if not isinstance(previous, dict):
                previous = {}
            complete_files = previous.get("render_signature") == signature and set(previous.get("videos", {})) == set(config["video"]["formats"]) and all(
                (directory / filename).is_file() and sha256(directory / filename) == previous.get("hashes", {}).get(fmt)
                for fmt, filename in previous.get("videos", {}).items()) and bool(previous.get("videos"))
            if complete_files:
                manifest = previous
            else:
                audio = synthesize(narration, directory / "voice.wav", config)
                videos = render_episode(script, audio, directory, config)
                manifest = {"episode_id": episode_id, "title": script["title"], "demo": demo,
                            "description": script["title"] + "\n\nSources :\n" + "\n".join(source["url"] for source in script["sources"]) + "\n\nVoix de synthèse. #IA #ActualiteIA",
                            "sources": script["sources"], "videos": {key: str(path.resolve()) for key, path in videos.items()},
                            "hashes": {key: sha256(path) for key, path in videos.items()},
                            "render_signature": signature, "duration_seconds": 60, "pipeline_version": __version__}
                write_json(manifest_path, manifest)
            if not demo:
                state.save(episode_id, "rendered", script)
            if publish:
                results = publish_episode(directory, config)
                write_json(directory / "publication.json", results)
                manifest["publication"] = results
                write_json(manifest_path, manifest)
                if any(item.get("status") not in {"succeeded", "export_only"} for item in results.values()):
                    state.save(episode_id, "publication_incomplete", script)
                    return {"status": "publication_incomplete", "episode_id": episode_id,
                            "directory": str(directory), "manifest": manifest}
            if not demo:
                state.save(episode_id, "complete", script)
            LOGGER.info("Épisode disponible : %s", directory)
            return {"status": "complete", "episode_id": episode_id, "directory": str(directory), "manifest": manifest}
        except Exception as exc:
            # Les exceptions tierces peuvent contenir des URLs signées ou jetons.
            if not demo:
                state.save(episode_id, "failed", error=type(exc).__name__)
            raise
