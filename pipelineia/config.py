"""Chargement et vérification de la configuration utilisateur."""
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv


def load_config(path: Path | str = "config.yaml") -> dict:
    """Charge les paramètres ; les chemins sont relatifs au fichier YAML."""
    path = Path(path).resolve()
    load_dotenv(path.parent / ".env", override=False)
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("La configuration doit être un objet YAML.")
    ZoneInfo(config.get("timezone", "Europe/Paris"))
    for key, default in (("output", "output"), ("state_db", "data/state.sqlite3"), ("logs", "logs")):
        value = Path(config.setdefault("paths", {}).get(key, default))
        config["paths"][key] = str(value if value.is_absolute() else path.parent / value)
    config["project_root"] = str(path.parent)
    if config.get("llm", {}).get("provider", "gemini_browser") not in {"gemini_browser", "gemini_cli", "gemini"}:
        raise ValueError("llm.provider doit être gemini_browser, gemini_cli ou gemini.")
    if config.get("video", {}).get("duration_seconds", 60) != 60:
        raise ValueError("Ce pipeline produit des vidéos de 60 secondes.")
    formats = config.get("video", {}).get("formats", {})
    if not formats:
        raise ValueError("Au moins un format vidéo est requis.")
    platforms = config.get("publishing", {}).get("platforms", [])
    if not isinstance(platforms, list) or any(p not in {"youtube", "instagram", "tiktok"} for p in platforms):
        raise ValueError("publishing.platforms doit lister youtube, instagram ou tiktok.")
    if platforms and "vertical" not in formats:
        raise ValueError("Le format vertical est requis pour les destinations sociales.")
    for name, size in formats.items():
        if name not in {"vertical", "square", "landscape"}:
            raise ValueError(f"Format vidéo inconnu : {name}")
        for dimension in ("width", "height"):
            value = size.get(dimension, 0)
            if not isinstance(value, int) or value < 128 or value % 2:
                raise ValueError("Les dimensions vidéo doivent être paires et >=128.")
    return config
