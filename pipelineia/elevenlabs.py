"""Voix ElevenLabs avec cache local, minutage et protection des appels payants."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

import requests
from filelock import FileLock


class ElevenLabsError(RuntimeError):
    """Erreur dont le message peut être affiché sans exposer de secret."""


def _hash(path: Path) -> str:
    """Calcule l'empreinte d'un fichier sans le charger en mémoire."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic(path: Path, data: bytes) -> None:
    """Remplace un fichier après écriture complète dans son dossier."""
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_write(path: Path, payload: dict) -> None:
    """Écrit des métadonnées locales sans clé API."""
    _atomic(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def _load(path: Path) -> dict:
    """Ignore les métadonnées absentes ou incomplètes."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _settings(text: str, config: dict) -> tuple[str, dict, dict]:
    """Valide les paramètres avant toute opération facturée."""
    settings = config.get("speech", config).get("elevenlabs", {})
    if not isinstance(settings, dict):
        raise ElevenLabsError("speech.elevenlabs doit être un objet de configuration.")
    voice = settings.get("voice_id") or os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not isinstance(voice, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", voice):
        raise ElevenLabsError("Renseigner ELEVENLABS_VOICE_ID ou speech.elevenlabs.voice_id.")
    model = settings.get("model_id")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", model):
        raise ElevenLabsError("Renseigner speech.elevenlabs.model_id avec un modèle TTS disponible.")
    output_format = settings.get("output_format", "mp3_44100_128")
    if output_format != "mp3_44100_128":
        raise ElevenLabsError("Cette intégration utilise output_format: mp3_44100_128.")
    try:
        maximum = int(settings.get("max_characters", 5000))
        timeout = int(settings.get("timeout_seconds", 120))
    except (TypeError, ValueError):
        raise ElevenLabsError("Limite de caractères ou délai ElevenLabs invalide.") from None
    if not isinstance(text, str) or not text.strip() or not 1 <= len(text) <= min(maximum, 40000):
        raise ElevenLabsError("Narration ElevenLabs vide ou supérieure à la limite de caractères configurée.")
    if not 1 <= timeout <= 300:
        raise ElevenLabsError("Le délai ElevenLabs doit être compris entre 1 et 300 secondes.")
    voice_settings = settings.get("voice_settings", {})
    if not isinstance(voice_settings, dict):
        raise ElevenLabsError("Les réglages de voix ElevenLabs doivent être un objet.")
    values = {}
    for name, default in (("stability", .5), ("similarity_boost", .75), ("style", 0.0), ("speed", 1.0)):
        value = voice_settings.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ElevenLabsError("Les réglages numériques de voix ElevenLabs sont invalides.")
        lower, upper = (.7, 1.2) if name == "speed" else (0.0, 1.0)
        if not lower <= value <= upper:
            raise ElevenLabsError("Un réglage de voix ElevenLabs dépasse l'intervalle autorisé.")
        values[name] = value
    boost = voice_settings.get("use_speaker_boost", True)
    if not isinstance(boost, bool):
        raise ElevenLabsError("use_speaker_boost doit être un booléen.")
    values["use_speaker_boost"] = boost
    payload = {"text": text, "model_id": model, "voice_settings": values}
    language = settings.get("language_code", "fr")
    if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2}", language):
        raise ElevenLabsError("language_code doit être un code de langue de deux lettres.")
    if model != "eleven_multilingual_v2":
        payload["language_code"] = language
    if "seed" in settings:
        seed = settings["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 4294967295:
            raise ElevenLabsError("La seed ElevenLabs doit être un entier positif sur 32 bits.")
        payload["seed"] = seed
    return voice, payload, {"output_format": output_format, "timeout": timeout}


def _alignment(value: object, text: str) -> dict | None:
    """Retient seulement un alignement complet, exact et chronologiquement valide."""
    if not isinstance(value, dict):
        return None
    chars = value.get("characters")
    starts = value.get("character_start_times_seconds")
    ends = value.get("character_end_times_seconds")
    if not all(isinstance(part, list) for part in (chars, starts, ends)) or not chars:
        return None
    if any(not isinstance(char, str) or len(char) != 1 for char in chars) or "".join(chars) != text:
        return None
    if len(chars) != len(starts) or len(chars) != len(ends):
        return None
    previous_start = previous_end = 0.0
    for start, end in zip(starts, ends):
        if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in (start, end)):
            return None
        if not 0 <= start <= end or start < previous_start or end < previous_end:
            return None
        previous_start, previous_end = start, end
    return {"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}


def _valid_wav(path: Path) -> bool:
    """Contrôle le conteneur WAV produit avant de réutiliser une sortie."""
    try:
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() > 0 and audio.getframerate() > 0 and audio.getsampwidth() == 2
    except (OSError, wave.Error, EOFError):
        return False


def _convert(source: Path, output: Path) -> None:
    """Décode le MP3 déjà payé en WAV PCM local, sans nouvel appel API."""
    from .speech import ffmpeg_binary
    descriptor, name = tempfile.mkstemp(prefix=output.stem + ".", suffix=".wav", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        result = subprocess.run([ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y",
                                 "-i", str(source.resolve()), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", str(temporary.resolve())],
                                capture_output=True, timeout=120)
        if result.returncode or not _valid_wav(temporary):
            raise ElevenLabsError("Décodage ElevenLabs impossible ; le MP3 payé reste en cache pour la reprise.")
        temporary.replace(output)
    except (subprocess.SubprocessError, OSError):
        raise ElevenLabsError("Conversion locale interrompue ; le MP3 payé reste en cache pour la reprise.") from None
    finally:
        temporary.unlink(missing_ok=True)


def synthesize_elevenlabs(text: str, output: Path, config: dict) -> Path:
    """Génère une voix une seule fois, puis réutilise l'audio et ses repères exacts."""
    voice, payload, options = _settings(text, config)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    mp3 = output.with_suffix(".elevenlabs.mp3")
    metadata_path = output.with_suffix(".elevenlabs.json")
    alignment_path = output.with_suffix(".alignment.json")
    digest = hashlib.sha256(json.dumps({"voice_id": voice, "payload": payload,
                                       "output_format": options["output_format"]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with FileLock(str(output) + ".elevenlabs.lock", timeout=30):
        metadata = _load(metadata_path)
        matching = metadata.get("cache_key") == digest
        if matching and output.is_file() and metadata.get("wav_sha256") == _hash(output) and _valid_wav(output):
            alignment = _alignment(metadata.get("alignment"), text)
            if alignment:
                _json_write(alignment_path, {"provider": "elevenlabs", "text": text, "alignment": alignment,
                                             "audio_sha256": metadata["wav_sha256"]})
            else:
                alignment_path.unlink(missing_ok=True)
            return output
        cached_mp3 = matching and mp3.is_file() and metadata.get("mp3_sha256") == _hash(mp3)
        if matching and metadata.get("status") == "ambiguous" and not cached_mp3:
            raise ElevenLabsError("Génération ElevenLabs précédente ambiguë : vérifier l'historique avant de réinitialiser ce cache ; aucun nouvel appel payé.")
        if (matching and metadata.get("status") in {"complete", "downloaded"} and not cached_mp3) or (metadata_path.exists() and not metadata):
            raise ElevenLabsError("Cache audio ElevenLabs incomplet ou corrompu ; vérifier l'historique avant une nouvelle génération payante.")
        if not cached_mp3:
            key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
            if not key:
                raise ElevenLabsError("Renseigner ELEVENLABS_API_KEY pour la voix ElevenLabs.")
            # Le marqueur précède le POST : même un arrêt du processus ne doit
            # pas répéter aveuglément une génération potentiellement facturée.
            metadata = {"cache_key": digest, "status": "ambiguous"}
            _json_write(metadata_path, metadata)
            try:
                response = requests.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
                    headers={"xi-api-key": key, "Content-Type": "application/json"},
                    params={"output_format": options["output_format"]}, json=payload,
                    timeout=options["timeout"], allow_redirects=False)
            except requests.RequestException:
                raise ElevenLabsError("Réponse ElevenLabs perdue ou délai dépassé ; vérifier l'historique avant une nouvelle génération payante.") from None
            if response.status_code != 200:
                # Un refus explicite ne peut contenir d'audio exploitable. Une
                # erreur serveur reste ambiguë et bloque les reprises aveugles.
                if 400 <= response.status_code < 500:
                    metadata["status"] = "rejected"
                    _json_write(metadata_path, metadata)
                if response.status_code in {401, 403}:
                    raise ElevenLabsError("ElevenLabs refuse l'accès : vérifier la clé API, les permissions et la voix choisie.")
                if response.status_code in {402, 429}:
                    raise ElevenLabsError("Crédits ou quota ElevenLabs indisponibles ; aucune recharge ni autre génération automatique.")
                raise ElevenLabsError(f"ElevenLabs a renvoyé HTTP {response.status_code} ; aucun nouvel essai automatique.")
            try:
                data = response.json()
                audio = base64.b64decode(data["audio_base64"], validate=True)
                if len(audio) < 16 or len(audio) > 50_000_000:
                    raise ValueError("audio")
            except (ValueError, TypeError, KeyError):
                raise ElevenLabsError("Réponse audio ElevenLabs invalide ; vérifier l'historique avant de régénérer.") from None
            alignment = _alignment(data.get("alignment"), text) or _alignment(data.get("normalized_alignment"), text)
            # L'audio est sauvé avant la conversion, donc une erreur FFmpeg
            # n'entraîne jamais un deuxième POST à la reprise.
            _atomic(mp3, audio)
            metadata = {"cache_key": digest, "status": "downloaded", "mp3_sha256": _hash(mp3), "alignment": alignment}
            _json_write(metadata_path, metadata)
        wav_ok = matching and output.is_file() and metadata.get("wav_sha256") == _hash(output) and _valid_wav(output)
        if not wav_ok:
            _convert(mp3, output)
        metadata["wav_sha256"] = _hash(output)
        metadata["status"] = "complete"
        _json_write(metadata_path, metadata)
        alignment = _alignment(metadata.get("alignment"), text)
        if alignment:
            _json_write(alignment_path, {"provider": "elevenlabs", "text": text, "alignment": alignment,
                                         "audio_sha256": metadata["wav_sha256"]})
        else:
            alignment_path.unlink(missing_ok=True)
        return output
