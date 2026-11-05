"""Accès optionnel à Gemini Web avec un profil dédié et sans API cachée."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock, Timeout as LockTimeout

LOGGER = logging.getLogger(__name__)
GEMINI_URL = "https://gemini.google.com/app"
EDITOR = 'rich-textarea [contenteditable="true"], div[contenteditable="true"][role="textbox"]'
RESPONSES = "model-response"
CONTENT_SELECTORS = (".model-response-text .markdown", ".response-content .markdown",
                     ".response-content", ".model-response-text", "message-content")
class BrowserError(RuntimeError):
    """Erreur lisible ne contenant ni identifiant ni contenu de page."""


STOP_NAME = re.compile(r"stop.*(?:generat|response)|arrêter.*(?:génér|réponse)", re.I)
BLOCKED = re.compile(r"(?:quota|limite).*(?:atteint|dépass|reached|exceeded)|"
                     r"(?:reached|exceeded).*(?:limit|quota)|too many requests|réessayez plus tard|try again later", re.I)


def parse_response(text: str) -> dict:
    """Accepte uniquement un objet JSON complet, éventuellement entouré d'un bloc."""
    text = text.strip()
    if len(text) > 100_000:
        raise ValueError("La réponse du navigateur est trop longue")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("Gemini Web doit renvoyer un objet JSON")
    return result


def profile_path(config: dict) -> Path:
    """Impose un profil propre au pipeline sous data/, jamais le profil personnel."""
    root = Path(config.get("project_root", Path(__file__).resolve().parent.parent)).resolve()
    data = (root / "data").resolve()
    value = Path(config.get("browser", {}).get("profile_dir", "data/google-browser"))
    profile = (value if value.is_absolute() else root / value).resolve()
    if profile == data or not profile.is_relative_to(data):
        raise ValueError("browser.profile_dir doit être un sous-dossier dédié de data/")
    return profile


@contextmanager
def _session(config: dict, *, login: bool = False) -> Iterator:
    """Ouvre le seul profil autorisé, verrouillé entre processus."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:
        raise BrowserError("Installer Playwright : python -m pip install playwright") from exc
    settings = config.get("browser", {})
    channel = settings.get("channel", "msedge" if os.name == "nt" else "chromium")
    if channel not in {"msedge", "chrome", "chromium"}:
        raise ValueError("browser.channel doit être msedge, chrome ou chromium")
    profile = profile_path(config)
    profile.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(profile.parent / (profile.name + ".lock")), timeout=1)
    try:
        with lock, sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(profile), channel=channel, headless=False if login else bool(settings.get("headless", False)),
                    accept_downloads=False, viewport={"width": 1280, "height": 900})
            except Error as exc:
                raise BrowserError("Navigateur indisponible ou profil déjà ouvert. Fermer sa fenêtre dédiée ; "
                                   "installer Chrome/Edge ou lancer python -m playwright install chromium "
                                   "puis choisir browser.channel: chromium.") from exc
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(10_000)
                yield page
            finally:
                try:
                    context.close()
                except Error:
                    pass  # La fenêtre peut avoir été fermée manuellement.
    except LockTimeout as exc:
        raise BrowserError("Le profil Gemini du pipeline est déjà utilisé par un autre processus") from exc
    except Error as exc:
        raise BrowserError("Gemini Web est inaccessible ou son interface a changé ; vérifier la fenêtre et relancer la connexion") from exc


def _check_access(page) -> None:
    """Signale connexion, vérification ou quota sans tenter de les contourner."""
    if "accounts.google.com" in page.url:
        raise BrowserError("Connexion Google requise : lancer python -m pipelineia.browser login")
    for selector in ('iframe[src*="recaptcha"]', 'iframe[src*="challenge"]'):
        challenge = page.locator(selector)
        if challenge.count() and challenge.first.is_visible():
            raise BrowserError("Vérification Google requise ; ouvrir la commande de connexion manuelle")
    alerts = page.get_by_role("alert")
    for index in range(min(alerts.count(), 5)):
        if BLOCKED.search(alerts.nth(index).inner_text()):
            raise BrowserError("Quota ou limite Gemini Web atteint ; traitement arrêté sans bascule API")


def extract_response(page) -> str:
    """Lit la dernière réponse affichée, sans utiliser les requêtes internes de Google."""
    responses = page.locator(RESPONSES)
    if not responses.count():
        return ""
    last = responses.last
    code = last.locator("pre code, code-block code")
    if code.count() == 1:
        # Évite les libellés « JSON / Copier le code » autour d'un bloc unique.
        return code.first.inner_text().strip()
    for selector in CONTENT_SELECTORS:
        content = last.locator(selector)
        if content.count():
            return content.last.inner_text().strip()
    # Aucun repli sur body : il pourrait contenir le prompt ou une ancienne réponse.
    return ""


def wait_for_response(page, config: dict) -> dict:
    """Attend un JSON stable après la fin de génération, avec délai maximal."""
    settings = config.get("browser", {})
    timeout = max(10, min(600, int(settings.get("timeout_seconds", 180))))
    stable_seconds = max(2, min(10, float(settings.get("stable_seconds", 4))))
    deadline = time.monotonic() + timeout
    previous = ""
    unchanged_since = time.monotonic()
    while time.monotonic() < deadline:
        _check_access(page)
        text = extract_response(page)
        if text != previous:
            previous, unchanged_since = text, time.monotonic()
        stop = page.get_by_role("button", name=STOP_NAME)
        generating = any(stop.nth(index).is_visible() for index in range(stop.count()))
        if text and not generating and time.monotonic() - unchanged_since >= stable_seconds:
            if BLOCKED.search(text) and not text.lstrip().startswith(("{", "```")):
                raise BrowserError("Gemini Web a signalé une limite ; traitement arrêté")
            try:
                return parse_response(text)
            except (ValueError, json.JSONDecodeError) as exc:
                raise BrowserError("Gemini Web n'a pas renvoyé le JSON attendu ; aucune vidéo ne sera inventée") from exc
        page.wait_for_timeout(1000)
    raise BrowserError("Délai Gemini Web dépassé : vérifier connexion, quota ou changement d'interface")


def browser_generate(prompt: str, config: dict) -> dict:
    """Soumet une rédaction textuelle à Gemini Web ; ne génère pas de vidéo Veo."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 120_000:
        raise ValueError("Prompt navigateur absent ou trop long")
    with _session(config) as page:
        page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60_000)
        _check_access(page)
        try:
            editor = page.locator(EDITOR).first
            editor.wait_for(state="visible", timeout=30_000)
        except Exception as exc:
            raise BrowserError("Champ Gemini introuvable : connecter le profil dédié ou vérifier l'interface") from exc
        if page.locator(RESPONSES).count():
            raise BrowserError("Gemini a restauré une ancienne conversation ; ouvrir une nouvelle discussion dans le profil dédié")
        editor.fill(prompt)
        # Entrée correspond au geste d'envoi ; aucune API privée ni jeton n'est utilisé.
        editor.press("Enter")
        return wait_for_response(page, config)


def login_browser(config: dict) -> None:
    """Laisse l'utilisateur connecter explicitement son profil dédié une première fois."""
    with _session(config, login=True) as page:
        page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60_000)
        LOGGER.info("Connectez le compte Google souhaité dans la fenêtre dédiée. Aucun prompt ne sera envoyé.")
        try:
            input("Une fois Gemini prêt à recevoir un message, appuyez sur Entrée ici pour conserver la session : ")
        except EOFError as exc:
            raise BrowserError("La connexion nécessite un terminal interactif ; relancer la commande login manuellement") from exc
        _check_access(page)
        if not page.locator(EDITOR).first.is_visible():
            raise BrowserError("La connexion n'est pas terminée ; relancer la commande login")
        (profile_path(config) / ".pipelineia-login").write_text("configured\n", encoding="utf-8")
    LOGGER.info("Profil Gemini enregistré localement ; aucun identifiant n'a été copié d'un autre navigateur.")


def main() -> None:
    """Expose seulement la connexion interactive ; aucune génération implicite."""
    parser = argparse.ArgumentParser(description="Connexion locale dédiée à Gemini Web")
    parser.add_argument("command", choices=["login"])
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    import yaml
    path = Path(args.config).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Configuration YAML invalide")
    config["project_root"] = str(path.parent)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        login_browser(config)
    except (BrowserError, ValueError) as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
