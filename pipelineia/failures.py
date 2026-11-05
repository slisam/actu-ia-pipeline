"""Classe les incidents sans transmettre le texte des exceptions aux notifications."""
import logging

from .alerts import notify_failure, resolve_episode

LOGGER = logging.getLogger(__name__)


def failure_code(stage: str, error: Exception) -> str:
    """Convertit les causes connues en codes limités, jamais en messages distants."""
    chain = []
    current = error
    for _ in range(8):
        if current is None or any(current is previous for previous in chain):
            break
        chain.append(current)
        current = current.__cause__ or current.__context__
    kinds = {type(item).__name__ for item in chain}
    # Ces textes servent uniquement à choisir un message fixe. Ils ne sont
    # ni enregistrés dans le journal d'alertes ni envoyés à Telegram.
    text = " ".join(str(item).lower() for item in chain)
    if stage == "voice":
        if any(term in text for term in ("ambigu", "historique", "réponse elevenlabs perdue")):
            return "uncertain"
        if any(term in text for term in ("crédits", "quota")):
            return "quota"
        if any(term in text for term in ("elevenlabs_api_key", "voice_id", "refuse l'accès")):
            return "credentials"
    if stage == "write":
        if "QuotaExhausted" in kinds or any(term in text for term in ("quota", "plafond quotidien", "budget de")):
            return "quota"
        if any(term in text for term in ("aucune clé", "clé gemini api absente", "clés autorisées")):
            return "credentials"
    if stage == "startup" and isinstance(error, (ValueError, FileNotFoundError)):
        return "configuration"
    return "failed"


def report_failure(config: dict, episode_id: str, stage: str, error: Exception,
                   *, demo: bool = False) -> None:
    """Signale un échec sans jamais remplacer l'exception de la production."""
    if demo:
        return
    try:
        notify_failure(config, episode_id, stage, code=failure_code(stage, error))
    except Exception:
        LOGGER.warning("Alerte non enregistrée ; l'erreur de production reste prioritaire.")
    try:
        error._pipeline_alert_handled = True
    except Exception:
        pass


def report_publication(config: dict, episode_id: str, results: dict) -> None:
    """Signale chaque destination en difficulté, indépendamment des réussites."""
    codes = {"failed": "failed", "uncertain": "uncertain", "not_configured": "credentials",
             "conflict": "conflict", "pending": "pending", "uploading": "pending"}
    for platform in ("youtube", "instagram", "tiktok"):
        item = results.get(platform, {})
        code = codes.get(item.get("status")) if isinstance(item, dict) else "failed"
        if code:
            try:
                notify_failure(config, episode_id, "publish", code=code, platform=platform)
            except Exception:
                LOGGER.warning("Alerte de publication non enregistrée ; consulter le résultat local.")


def report_recovery(config: dict, episode_id: str, *, demo: bool = False) -> None:
    """Annule les alertes en attente lorsque l'épisode est réellement terminé."""
    if not demo:
        try:
            resolve_episode(config, episode_id)
        except Exception:
            LOGGER.warning("Résolution des alertes indisponible ; la production a réussi.")
