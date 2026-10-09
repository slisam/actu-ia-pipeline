"""Configuration du logging : console + fichier dans logs/."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
LOGS_DIR = RACINE / "logs"
FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configurer_logging(nom_module: str, niveau: int = logging.INFO,
                       dossier_logs: Path | None = None) -> logging.Logger:
    """Configure et retourne un logger écrivant en console et dans logs/.

    Args:
        nom_module: nom du module (ex. "collect"), utilisé pour le fichier de log.
        niveau: niveau de logging (INFO par défaut).
        dossier_logs: dossier alternatif (tests).
    """
    dossier = dossier_logs or LOGS_DIR
    dossier.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(nom_module)
    logger.setLevel(niveau)
    if logger.handlers:  # évite les doublons si appelé plusieurs fois
        return logger
    formatteur = logging.Formatter(FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(formatteur)
    logger.addHandler(console)
    fichier = logging.FileHandler(
        dossier / f"{nom_module}_{datetime.now():%Y%m%d}.log", encoding="utf-8"
    )
    fichier.setFormatter(formatteur)
    logger.addHandler(fichier)
    return logger
