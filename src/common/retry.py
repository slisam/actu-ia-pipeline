"""Décorateur de retry avec backoff exponentiel pour les appels API."""

from __future__ import annotations

import logging
from typing import Any, Callable

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


def retry_api(tentatives: int = 4, attente_min: float = 1.0,
              attente_max: float = 30.0,
              exceptions: tuple[type[BaseException], ...] = (Exception,)) -> Callable[..., Any]:
    """Retourne un décorateur qui relance une fonction en cas d'erreur.

    L'attente double à chaque essai (1s, 2s, 4s...) jusqu'à attente_max.
    Après le dernier essai, l'exception d'origine est relevée.

    Args:
        tentatives: nombre maximal d'essais.
        attente_min: attente initiale en secondes.
        attente_max: attente maximale en secondes.
        exceptions: types d'exceptions qui déclenchent un nouvel essai.
    """
    return retry(
        stop=stop_after_attempt(tentatives),
        wait=wait_exponential(multiplier=attente_min, max=attente_max),
        retry=retry_if_exception_type(exceptions),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
