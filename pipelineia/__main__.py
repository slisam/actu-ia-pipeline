"""Commandes simples de diagnostic, démonstration et production."""
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_config
from .publish import publishing_readiness
from .run import run_episode
from .speech import ffmpeg_binary
from .state import State
from .writer import WriterError
from .browser import BrowserError

LOGGER = logging.getLogger("pipelineia")


def doctor(config: dict) -> int:
    """Vérifie les composants sans appeler de modèle ni exposer les secrets."""
    checks = {}
    try:
        binary = ffmpeg_binary()
        result = subprocess.run([binary, "-version"], capture_output=True, timeout=20)
        checks["ffmpeg"] = result.returncode == 0
    except Exception:
        checks["ffmpeg"] = False
    provider = config.get("llm", {}).get("provider", "api_pool")
    if provider == "api_pool":
        from .llm_pool import readiness
        pool = readiness(config)
        checks["cles_gemini"] = pool
        checks["api_gratuite_configuree"] = any(item.get("ready", False) for item in pool.values())
        checks["api_note"] = "Présence locale uniquement : niveau gratuit et droits du projet à vérifier dans AI Studio. Un quota atteint met son projet en pause ; une clé d'un autre projet disponible est essayée immédiatement."
    elif provider == "gemini_browser":
        profile = Path(config.get("browser", {}).get("profile_dir", "data/google-browser"))
        if not profile.is_absolute():
            profile = Path(config["project_root"]) / profile
        checks["profil_google_dedie_prepare"] = (profile / ".pipelineia-login").is_file()
        checks["navigateur_note"] = "Connexion et quota non vérifiés par doctor ; lancer python -m pipelineia.browser login pour connecter le compte Pro."
    elif provider == "gemini_cli":
        command = config["llm"].get("cli_command", "gemini")
        checks["gemini_cli_installe"] = bool(shutil.which(command))
        # Ne lit pas le contenu des identifiants et ne déclenche pas de connexion.
        cli_home = Path(os.environ.get("GEMINI_CLI_HOME", str(Path.home())))
        checks["connexion_google_presente"] = (cli_home / ".gemini" / "oauth_creds.json").is_file()
    else:
        checks["cle_gemini_presente"] = bool(os.getenv("GEMINI_API_KEY"))
    speech = config.get("speech", {}).get("provider", "auto")
    if speech == "auto":
        speech = "system" if os.name == "nt" else "espeak"
    checks["voix_fournisseur"] = speech
    if speech == "espeak":
        checks["voix_locale_installee"] = bool(shutil.which("espeak-ng") or shutil.which("espeak"))
    elif speech == "system":
        checks["voix_locale_installee"] = os.name == "nt"
        checks["voix_note"] = "Une voix fr-FR doit être installée ; demo vérifie la synthèse réelle."
    elif speech == "google":
        checks["voix_note"] = "Identifiants ADC et facturation Cloud à vérifier côté Google."
    else:
        checks["voix_locale_installee"] = False
    checks["publication"] = publishing_readiness(config)
    LOGGER.info("Diagnostic (présence locale, pas validation des droits distants) :\n%s", json.dumps(checks, ensure_ascii=False, indent=2))
    publication_ok = all(item.get("ready", False) or item.get("status") == "export_only"
                         for item in checks["publication"].values())
    return 0 if all(value is not False for value in checks.values()) and publication_ok else 2


def main(argv: list[str] | None = None) -> int:
    """Expose une CLI sans déclencher de génération par simple diagnostic."""
    parser = argparse.ArgumentParser(description="Pipelineia : actualités IA en vidéos de 60 secondes")
    parser.add_argument("--config", default="config.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Diagnostic sans génération ni dépense")
    demo = commands.add_parser("demo", help="Exemple hors ligne, sans actualité inventée")
    demo.add_argument("--quick", action="store_true", help="Résolution réduite pour vérifier rapidement")
    demo.add_argument("--silent", action="store_true", help="Sans voix, pour CI seulement")
    run = commands.add_parser("run", help="Un épisode quotidien ; reprend aussi les épisodes interrompus")
    run.add_argument("--publish", action="store_true", help="Publier vers les destinations configurées")
    run.add_argument("--episode-id", help="Reprendre un épisode précis AAAA-MM-JJ-actu-ia")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    try:
        config = load_config(args.config)
        log_dir = Path(config["paths"]["logs"])
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(log_dir / "pipeline.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s : %(message)s"))
        logging.getLogger().addHandler(handler)
        if args.command == "doctor":
            return doctor(config)
        if args.command == "demo":
            result = run_episode(config, demo=True, quick=args.quick, silent=args.silent)
            LOGGER.info("Démo : %s", result["directory"])
            return 0
        episode_ids = [args.episode_id] if args.episode_id else []
        if not episode_ids:
            if args.publish:
                episode_ids.extend(State(config["paths"]["state_db"]).unfinished())
            today = datetime.now(ZoneInfo(config.get("timezone", "Europe/Paris"))).date().isoformat() + "-actu-ia"
            if today not in episode_ids:
                episode_ids.append(today)
        failed = False
        for episode_id in episode_ids:
            try:
                result = run_episode(config, publish=args.publish, episode_id=episode_id)
                LOGGER.info("Résultat : %s (%s)", result["status"], episode_id)
                failed |= result["status"] == "publication_incomplete"
            except Exception as exc:
                LOGGER.error("Épisode %s interrompu (%s). Le script validé est conservé.", episode_id, type(exc).__name__)
                if isinstance(exc, (WriterError, BrowserError, ValueError)):
                    LOGGER.error("%s", str(exc))
                failed = True
        return 2 if failed else 0
    except Exception as exc:
        # Pas de traceback/corps distant : les exceptions réseau peuvent contenir des jetons.
        safe_types = (ValueError, FileNotFoundError, WriterError, BrowserError)
        message = str(exc) if isinstance(exc, safe_types) else "Consulter le diagnostic local ; aucun basculement vers une API payante."
        LOGGER.error("%s : %s", type(exc).__name__, message)
        return 1


if __name__ == "__main__":
    sys.exit(main())
