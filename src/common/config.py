"""Chargement de la configuration (config.yaml) et des secrets (.env)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parents[2]
CONFIG_PATH = RACINE / "config.yaml"
PROMPTS_DIR = RACINE / "prompts"
OUTPUT_DIR = RACINE / "output"


class ConfigError(Exception):
    """Erreur de configuration (fichier ou clé manquante)."""


def charger_config(chemin: Path | None = None) -> dict[str, Any]:
    """Charge config.yaml et retourne son contenu sous forme de dictionnaire.

    Args:
        chemin: chemin alternatif du fichier (utile pour les tests).

    Raises:
        ConfigError: si le fichier est introuvable ou invalide.
    """
    chemin = chemin or CONFIG_PATH
    if not chemin.exists():
        raise ConfigError(f"Fichier de configuration introuvable : {chemin}")
    try:
        with chemin.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigError(f"config.yaml invalide : {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("config.yaml doit contenir un dictionnaire.")
    return data


def obtenir_cle(nom: str) -> str:
    """Retourne la valeur d'une clé API depuis .env / l'environnement.

    Raises:
        ConfigError: si la clé est absente ou vide.
    """
    load_dotenv(RACINE / ".env")
    valeur = os.getenv(nom, "").strip()
    if not valeur:
        raise ConfigError(
            f"La clé {nom} est manquante. Copiez .env.example en .env "
            f"et renseignez {nom}."
        )
    return valeur


def charger_prompt(nom: str) -> str:
    """Lit un prompt depuis prompts/<nom>.md.

    Raises:
        ConfigError: si le fichier de prompt n'existe pas.
    """
    chemin = PROMPTS_DIR / f"{nom}.md"
    if not chemin.exists():
        raise ConfigError(f"Prompt introuvable : {chemin}")
    return chemin.read_text(encoding="utf-8")


def dossier_episode(id_episode: str) -> Path:
    """Retourne (et crée si besoin) le dossier output/<id_episode>/."""
    dossier = OUTPUT_DIR / id_episode
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier
