"""Repérage des conversations privées du bot, sans afficher son jeton."""
import os
import re

import requests


class TelegramSetupError(RuntimeError):
    """Erreur de connexion au bot sans détail sensible."""


def private_chat_ids() -> list[str]:
    """Lit les mises à jour disponibles sans envoyer de message ni les confirmer."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,200}", token):
        raise TelegramSetupError("Renseigner TELEGRAM_BOT_TOKEN dans .env avant de chercher la conversation.")
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                params={"limit": 100, "timeout": 0, "allowed_updates": '["message"]'},
                                timeout=10, allow_redirects=False)
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            raise TelegramSetupError("Telegram refuse la lecture ; vérifier la clé et utiliser un bot dédié sans webhook.")
        updates = data.get("result")
        if not isinstance(updates, list):
            raise TelegramSetupError("Réponse Telegram inexploitable.")
        identifiers = set()
        for update in updates:
            if not isinstance(update, dict):
                continue
            message = update.get("message", {})
            chat = message.get("chat", {}) if isinstance(message, dict) else {}
            if isinstance(chat, dict) and chat.get("type") == "private":
                identifier = str(chat.get("id", ""))
                if re.fullmatch(r"[1-9][0-9]{0,19}", identifier):
                    identifiers.add(identifier)
        return sorted(identifiers)
    except (requests.RequestException, ValueError, TypeError):
        raise TelegramSetupError("Lecture Telegram impossible ; aucune clé ni réponse distante n'est affichée.") from None
