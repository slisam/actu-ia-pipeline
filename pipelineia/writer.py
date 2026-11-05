"""Rédaction et contrôle de scripts sourcés, sans repli fictif."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


class WriterError(RuntimeError):
    """Erreur locale dont le message fixe peut être affiché sans exposer de secret."""


def word_count(text: str) -> int:
    """Compte les mots oraux en conservant apostrophes et traits d'union internes."""
    return len(re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", text, re.UNICODE))


def _json(text: str) -> dict:
    """Décode un objet JSON complet ; refuse les réponses partielles ou narratives."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("Le modèle doit renvoyer un objet JSON")
    return result


def _normal(text: str) -> str:
    """Normalise uniquement les espaces pour contrôler une citation exacte."""
    return " ".join(text.split())


def validate_script(script: dict, articles: list[dict], config: dict | None = None) -> dict:
    """Contrôle structure, durée orale, hook et preuves, puis fixe les sources."""
    settings = (config or {}).get("script", {})
    originals = {article["id"]: article for article in articles}
    title, hook, scenes = script.get("title"), script.get("hook"), script.get("scenes")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError("Titre absent ou trop long")
    if not isinstance(hook, str) or not 5 <= word_count(hook) <= 16:
        raise ValueError("Le hook doit contenir entre 5 et 16 mots")
    if not isinstance(scenes, list) or not 4 <= len(scenes) <= 6:
        raise ValueError("Le script doit comporter de 4 à 6 scènes")
    selected: set[str] = set()
    excerpts: set[str] = set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("Scène invalide")
        narration, screen = scene.get("narration"), scene.get("on_screen")
        if not isinstance(narration, str) or not narration.strip() or len(narration) > 2000:
            raise ValueError("Narration absente ou trop longue")
        if not isinstance(screen, str) or not screen.strip() or word_count(screen) > 14:
            raise ValueError("Texte à l'écran absent ou trop long")
        ids, evidence = scene.get("source_ids"), scene.get("evidence")
        if not isinstance(ids, list) or not ids or any(not isinstance(s, str) or s not in originals for s in ids):
            raise ValueError("Identifiant de source inconnu")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("Chaque scène doit posséder une preuve")
        proved = set()
        for item in evidence:
            if not isinstance(item, dict) or item.get("source_id") not in ids:
                raise ValueError("Preuve sans source correspondante")
            quote = item.get("quote")
            if not isinstance(quote, str) or not 3 <= word_count(quote) <= 20:
                raise ValueError("Citation de preuve absente ou trop longue")
            if _normal(quote) not in _normal(originals[item["source_id"]]["text"]):
                raise ValueError("La preuve n'est pas une citation exacte de la source")
            proved.add(item["source_id"])
            excerpts.add(_normal(quote))
        if proved != set(ids):
            raise ValueError("Une source de la scène ne possède pas de preuve")
        selected.update(ids)
    if len(selected) != 1:
        raise ValueError("Un épisode doit traiter une seule actualité")
    if sum(word_count(excerpt) for excerpt in excerpts) > 25:
        raise ValueError("Trop de texte source cité : réutiliser un extrait court")
    if not _normal(scenes[0]["narration"]).startswith(_normal(hook)):
        raise ValueError("Le hook doit ouvrir la narration de la première scène")
    spoken = " ".join(scene["narration"] for scene in scenes)
    count = word_count(spoken)
    minimum = int(settings.get("min_words", 120))
    maximum = int(settings.get("max_words", 155))
    if not minimum <= count <= maximum:
        raise ValueError(f"Durée orale invalide : {count} mots, attendu {minimum} à {maximum}")
    if re.search(r"https?://|<script|```", spoken, re.I):
        raise ValueError("La narration contient du code ou une URL")
    french_markers = re.findall(r"\b(?:le|la|les|un|une|des|du|de|pour|avec|dans|et|est|ce|cette|son|ses|qui)\b", spoken.lower())
    if len(french_markers) < 10:
        raise ValueError("La narration doit être en français")
    cleaned = {"title": title.strip(), "hook": hook.strip(), "scenes": scenes,
               "sources": [{key: originals[sid].get(key, "") for key in
                            ("id", "title", "url", "published_at", "source")} for sid in sorted(selected)],
               "word_count": count}
    return cleaned


def _validate_verification(check: dict, script: dict) -> None:
    """Refuse tout contrôle incomplet ou toute affirmation déclarée non étayée."""
    if any(check.get(key) is not True for key in ("supported", "title_supported", "hook_supported")):
        raise ValueError("Le contrôle éditorial a rejeté le titre, le hook ou les faits")
    checks = check.get("checks")
    if not isinstance(checks, list) or len(checks) != len(script["scenes"]):
        raise ValueError("Le contrôle éditorial doit couvrir chaque scène")
    if {item.get("scene") for item in checks if isinstance(item, dict)} != set(range(1, len(checks) + 1)):
        raise ValueError("Le contrôle éditorial possède des scènes manquantes ou dupliquées")
    if any(not isinstance(item, dict) or item.get("supported") is not True for item in checks):
        raise ValueError("Une scène contient des faits non justifiés")


class _Generator:
    """Applique un budget de requêtes à une session de rédaction."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.settings = config.get("llm", {})
        self.requests = 0
        self.pool = None
        self.limit = max(2, min(6, int(self.settings.get("max_requests_per_run", 4))))

    def generate(self, prompt: str) -> dict:
        """Appelle le fournisseur choisi sans bascule payante implicite."""
        if self.requests >= self.limit:
            raise WriterError("Budget de requêtes atteint pour cet épisode")
        self.requests += 1
        provider = self.settings.get("provider", "gemini_cli")
        if provider == "api_pool":
            from .llm_pool import APIPool, PoolError

            try:
                if self.pool is None:
                    self.pool = APIPool(self.config)
                return self.pool.generate(prompt)
            except PoolError as exc:
                raise WriterError(str(exc)) from None
        if provider == "gemini_browser":
            from .browser import browser_generate

            result = browser_generate(prompt, self.config)
            return _json(result) if isinstance(result, str) else result
        model = (self.settings.get("cli_model", "auto") if provider == "gemini_cli" else
                 self.settings.get("model") or self.settings.get("fast_model"))
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", model):
            raise ValueError("Configurer llm.model avec un modèle Gemini disponible")
        if provider == "gemini_cli":
            return self._cli(prompt, model)
        if provider != "gemini":
            raise ValueError("llm.provider doit être api_pool, gemini_browser, gemini_cli ou gemini")
        return self._api(prompt, model)

    def _api(self, prompt: str, model: str) -> dict:
        """Appelle Gemini REST avec JSON obligatoire et sortie bornée."""
        key = os.environ.get(self.settings.get("api_key_env", "GEMINI_API_KEY"))
        if not key:
            raise WriterError("Clé Gemini API absente ; choisir gemini_cli pour le compte Google connecté")
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json",
                                           "maxOutputTokens": min(8192, int(self.settings.get("max_output_tokens", 4096))) }},
                timeout=min(180, int(self.settings.get("timeout_seconds", 120))))
            if not response.ok:
                # Ne jamais recopier le corps ou l'URL d'erreur contenant des secrets.
                raise WriterError(f"Gemini API a renvoyé HTTP {response.status_code}")
            data = response.json()
            candidate = data.get("candidates", [{}])[0]
            if candidate.get("finishReason") not in {None, "STOP"}:
                raise ValueError("Gemini a interrompu ou filtré la rédaction")
            text = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", [])
                           if not part.get("thought"))
            return _json(text)
        except requests.RequestException as exc:
            raise WriterError("Gemini API inaccessible") from exc

    def _cli(self, prompt: str, model: str) -> dict:
        """Utilise l'OAuth existant de Gemini CLI avec outils et extensions bloqués."""
        executable = shutil.which(self.settings.get("cli_command", "gemini"))
        if not executable:
            raise WriterError("Gemini CLI absent : installer @google/gemini-cli puis lancer gemini pour se connecter")
        cli_home = Path(os.environ.get("GEMINI_CLI_HOME", str(Path.home())))
        if not (cli_home / ".gemini" / "oauth_creds.json").is_file():
            raise WriterError("Connexion Google CLI absente : lancer gemini et choisir Se connecter avec Google")
        with tempfile.TemporaryDirectory(prefix="pipelineia-writer-") as folder:
            working = Path(folder)
            (working / ".git").mkdir()  # Arrête la recherche de contexte dans les parents.
            (working / ".gemini").mkdir()
            # ignoreLocalEnv ne suffit pas à ignorer ~/.gemini/.env. Ce fichier
            # vide arrête la recherche avant tout fichier personnel ou parent.
            (working / ".gemini" / ".env").write_text("", encoding="utf-8")
            policy = working / "no-tools.toml"
            policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n', encoding="utf-8")
            settings = working / ".gemini" / "settings.json"
            settings_payload = {
                "hooksConfig": {"enabled": False}, "skills": {"enabled": False},
                "admin": {"mcp": {"enabled": False}, "extensions": {"enabled": False},
                          "skills": {"enabled": False}},
                "mcp": {"allowed": ["pipelineia-no-mcp-server"]}, "security": {"auth": {"selectedType": "oauth-personal"},
                                                             "disableYoloMode": True},
                "general": {"maxAttempts": 1, "enableAutoUpdate": False},
                "model": {"maxSessionTurns": 1},
                "modelConfigs": {"customOverrides": [{"match": {"isChatModel": True}, "modelConfig": {
                    "generateContentConfig": {
                        "maxOutputTokens": min(8192, int(self.settings.get("max_output_tokens", 4096))),
                        "toolConfig": {"functionCallingConfig": {"mode": "NONE"}}}}}]},
                "context": {"fileName": "PIPELINEIA_NO_CONTEXT.md", "loadFromIncludeDirectories": False},
                "advanced": {"ignoreLocalEnv": True}, "telemetry": {"enabled": False},
            }
            settings_text = json.dumps(settings_payload)
            settings.write_text(settings_text, encoding="utf-8")
            environment = os.environ.copy()
            for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GEMINI_SYSTEM_MD",
                        "GEMINI_WRITE_SYSTEM_MD", "GOOGLE_GENAI_USE_GCA", "GOOGLE_CLOUD_ACCESS_TOKEN",
                        "GEMINI_CLI_SYSTEM_SETTINGS_PATH", "GEMINI_CLI_SYSTEM_DEFAULTS_PATH"):
                environment.pop(key, None)
            environment.update(GEMINI_CLI_TRUST_WORKSPACE="true", GEMINI_TELEMETRY_ENABLED="false",
                               NO_BROWSER="true")
            if os.name == "nt":
                # Windows PowerShell doit retrouver ses propres modules Get-Acl,
                # sans hériter du chemin des modules de PowerShell 7.
                environment.pop("PSModulePath", None)
            command = [executable, "--prompt", "Réponds au texte reçu sur l'entrée standard.",
                       "--output-format", "json", "--extensions", "none", "--model", model,
                       "--admin-policy", str(policy), "--approval-mode", "default"]
            try:
                result = subprocess.run(command, input=prompt, capture_output=True, text=True,
                                        encoding="utf-8", cwd=working, env=environment, shell=False,
                                        timeout=min(300, int(self.settings.get("timeout_seconds", 180))))
            except subprocess.TimeoutExpired as exc:
                raise WriterError("Gemini CLI a dépassé son délai ; vérifier connexion et quotas") from exc
            if result.returncode:
                if "UNSUPPORTED_CLIENT" in result.stderr or "This client is no longer supported" in result.stderr:
                    raise WriterError("Google refuse actuellement ce client Gemini CLI pour le compte connecté "
                                      "(UNSUPPORTED_CLIENT). Vérifier l'accès du compte et les clients officiellement "
                                      "pris en charge ; aucune API payante n'a été activée.")
                raise WriterError(f"Gemini CLI a échoué (code {result.returncode}) ; vérifier connexion, modèle et quota")
            if "Skipping system settings file" in result.stderr:
                raise WriterError("Gemini CLI a ignoré la configuration de protection ; génération bloquée.")
            if len(result.stdout) > 100_000:
                raise ValueError("Réponse Gemini CLI trop longue")
            envelope = _json(result.stdout)
            if envelope.get("error"):
                raise WriterError("Gemini CLI a renvoyé une erreur")
            return _json(envelope.get("response", ""))


def write_script(articles: list[dict], config: dict) -> dict:
    """Produit un script vérifié ; bloque l'épisode si les preuves sont insuffisantes."""
    if not articles:
        raise ValueError("Aucune actualité récente exploitable")
    settings = config.get("llm", {})
    max_input = max(8000, min(100_000, int(settings.get("max_input_chars", 45000))))
    context: list[dict] = []
    remaining = max_input
    for article in articles[:8]:
        if remaining < 1000:
            break
        item = dict(article)
        item["text"] = str(item.get("text", ""))[:min(14000, remaining)]
        remaining -= len(json.dumps(item, ensure_ascii=False))
        if len(item["text"]) >= 200:
            context.append(item)
    if not context:
        raise ValueError("Textes des sources insuffisants")
    generator = _Generator(config)
    write_prompt = (ROOT / "prompts" / "write.md").read_text(encoding="utf-8")
    verify_prompt = (ROOT / "prompts" / "verify.md").read_text(encoding="utf-8")
    source_text = json.dumps(context, ensure_ascii=False)
    last_error = ""
    for attempt in range(max(1, min(2, int(settings.get("generation_attempts", 2))))):
        try:
            raw = generator.generate(write_prompt + "\nARTICLES_JSON:\n" + source_text
                                     + ("\nErreur précédente à corriger : " + last_error if last_error else ""))
            script = validate_script(raw, context, config)
            verification = generator.generate(verify_prompt + "\nARTICLES_JSON:\n" + source_text
                                              + "\nSCRIPT_JSON:\n" + json.dumps(script, ensure_ascii=False))
            _validate_verification(verification, script)
            script["verification"] = verification
            script["llm_requests"] = generator.requests
            if generator.pool is not None:
                script["llm_http_attempts"] = generator.pool.requests
            return script
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            LOGGER.warning("Script rejeté à la tentative %d : %s", attempt + 1, last_error)
            if attempt == 0:
                time.sleep(1)
    raise ValueError("Épisode bloqué après contrôle : " + last_error)
