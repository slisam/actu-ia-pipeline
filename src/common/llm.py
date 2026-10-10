"""
Module LLM : interface unifiée avec l'API Gemini.

Gère :
- Chargement des prompts depuis prompts/*.md
- Substitution des variables {{variable}}
- Appel à Gemini (fast ou quality model)
- Validation et parsing du JSON (optionnel)
- Retry avec backoff exponentiel
"""

import json
import logging
from pathlib import Path
from typing import Any

import google.generativeai as genai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .config import get_config

logger = logging.getLogger(__name__)


def load_prompt(prompt_file: str, variables: dict[str, Any] | None = None) -> str:
    """
    Charge un prompt depuis prompts/{prompt_file}.md et remplace les variables.

    Args:
        prompt_file: Nom du fichier (ex: "script_generation.md")
        variables: Dict {variable_name: value} pour remplacer {{variable_name}}

    Returns:
        Prompt complété (string)

    Raises:
        FileNotFoundError: Si le fichier prompt n'existe pas
        KeyError: Si une variable {{...}} n'est pas dans le dict variables
    """
    config = get_config()
    prompt_path = Path(config.paths["prompts"]) / prompt_file

    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8")

    if variables:
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            content = content.replace(placeholder, str(value))

    return content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception),
    before_sleep=lambda retry_state: logger.warning(
        f"Retry LLM call (attempt {retry_state.attempt_number}): "
        f"{retry_state.outcome.exception()}"
    ),
)
def _call_gemini(
    prompt: str, model: str, temperature: float = 0.7, json_output: bool = False
) -> str:
    """
    Appel à l'API Gemini avec retry automatique.

    Args:
        prompt: Texte du prompt
        model: Nom du modèle (ex: "gemini-1.5-flash")
        temperature: Créativité (0.0-1.0)
        json_output: Si True, force response_mime_type="application/json"

    Returns:
        Texte brut de la réponse

    Raises:
        Exception: Erreur API après 3 tentatives
    """
    config = get_config()
    genai.configure(api_key=config.env.get("GEMINI_API_KEY"))

    client = genai.Client()
    generation_config = genai.types.GenerationConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_output else "text/plain",
    )

    response = client.models.generate_content(
        model=f"models/{model}",
        contents=prompt,
        generation_config=generation_config,
    )

    return response.text


def generate(
    prompt_file: str,
    variables: dict[str, Any] | None = None,
    model: str = "fast",
    temperature: float = 0.7,
    json_output: bool = False,
) -> str | dict:
    """
    Interface principale : charger prompt + appeler Gemini + parser JSON (optionnel).

    Args:
        prompt_file: Nom du fichier prompt (ex: "script_generation.md")
        variables: Dict {variable_name: value} pour remplacer {{variable_name}}
        model: "fast" (gemini-1.5-flash) ou "quality" (gemini-1.5-pro)
        temperature: Créativité (0.0-1.0), défaut 0.7
        json_output: Si True, retourne un dict parsé (au lieu de string)

    Returns:
        String brut, ou dict si json_output=True

    Example:
        >>> script = generate(
        ...     "script_generation.md",
        ...     {"topic": "IA", "duration": "60s"},
        ...     model="quality"
        ... )
        >>> data = generate(
        ...     "extract_info.md",
        ...     {"text": "..."},
        ...     json_output=True
        ... )
    """
    config = get_config()

    # Résoudre le modèle
    if model == "fast":
        model_name = config.config.get("llm", {}).get("fast_model", "gemini-1.5-flash")
    elif model == "quality":
        model_name = config.config.get("llm", {}).get("quality_model", "gemini-1.5-pro")
    else:
        raise ValueError(f"Invalid model: {model}. Use 'fast' or 'quality'.")

    logger.info(
        f"Generating content: prompt={prompt_file}, model={model_name}, json={json_output}"
    )

    # Charger et remplacer variables
    prompt = load_prompt(prompt_file, variables)

    # Appeler Gemini
    response_text = _call_gemini(
        prompt, model_name, temperature=temperature, json_output=json_output
    )

    # Parser JSON si demandé
    if json_output:
        try:
            result = json.loads(response_text)
            logger.debug(f"JSON parsed successfully: {len(str(result))} chars")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise ValueError(f"Invalid JSON from LLM: {response_text}") from e

    return response_text
