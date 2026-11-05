"""Synthèse vocale économique, avec fournisseurs explicites et sans compte tournant."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

LOGGER = logging.getLogger(__name__)


def _system(text: str, output: Path, config: dict) -> None:
    """Utilise une voix française Windows SAPI déjà installée, sans service externe."""
    binary = shutil.which("powershell.exe")
    if os.name != "nt" or not binary:
        raise RuntimeError("speech.provider=system nécessite Windows et une voix française installée.")
    request = {"text": text, "output": str(output.resolve()),
               "voice": config.get("system_voice", ""), "rate": int(config.get("system_rate", -1)),
               "culture": config.get("language_code", "fr-FR")}
    # Le texte et les chemins sont des données JSON, jamais du code PowerShell interpolé.
    script = r"""$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$request = Get-Content -LiteralPath $env:PIPELINEIA_SPEECH_REQUEST -Raw -Encoding UTF8 | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq $request.culture })
    if ($voices.Count -eq 0) { throw 'Aucune voix française Windows disponible. Installer une voix fr-FR dans les paramètres Langue de Windows.' }
    if ($request.voice) {
        $selected = @($voices | Where-Object { $_.VoiceInfo.Name -eq $request.voice })
        if ($selected.Count -eq 0) { throw 'La voix Windows configurée ne correspond pas à une voix française installée.' }
        $synth.SelectVoice($selected[0].VoiceInfo.Name)
    } else { $synth.SelectVoice($voices[0].VoiceInfo.Name) }
    $synth.Rate = [Math]::Max(-10, [Math]::Min(10, $request.rate))
    $synth.SetOutputToWaveFile($request.output)
    $synth.Speak($request.text)
} finally { $synth.Dispose() }
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    with tempfile.TemporaryDirectory(prefix="pipelineia-speech-") as directory:
        request_path = Path(directory) / "request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        environment = os.environ.copy()
        environment["PIPELINEIA_SPEECH_REQUEST"] = str(request_path)
        result = subprocess.run([binary, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                env=environment, capture_output=True, timeout=180)
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace")[-1400:]
            raise RuntimeError(f"Échec de la voix Windows : {detail}")


def ffmpeg_binary() -> str:
    """Trouve FFmpeg installé ou le binaire portable de imageio-ffmpeg."""
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _google(text: str, config: dict) -> bytes:
    """Appelle Cloud Text-to-Speech avec les identifiants applicatifs Google."""
    import google.auth
    import requests
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())
    headers = {"Authorization": f"Bearer {credentials.token}"}
    quota_project = getattr(credentials, "quota_project_id", None)
    if quota_project:
        headers["x-goog-user-project"] = quota_project
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": config.get("language_code", "fr-FR"),
            "name": config["google_voice"],
        },
        "audioConfig": {"audioEncoding": "LINEAR16", "speakingRate": config.get("speaking_rate", 1.0)},
    }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8),
           retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)), reraise=True)
    def request() -> bytes:
        response = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize",
                                 headers=headers, json=payload, timeout=60)
        # Aucun changement de compte ou passage automatique à une offre payante.
        response.raise_for_status()
        return base64.b64decode(response.json()["audioContent"], validate=True)

    return request()


def synthesize(text: str, output: Path, config: dict) -> Path:
    """Crée une voix WAV locale, Google ou ElevenLabs ; demo est réservé aux essais."""
    output = Path(output)
    if not text.strip():
        raise ValueError("Le texte de narration est vide.")
    speech = config.get("speech", config)
    provider = speech.get("provider", "auto")
    if provider == "auto":
        provider = "system" if os.name == "nt" else "espeak"
    output.parent.mkdir(parents=True, exist_ok=True)
    if provider == "demo":
        duration = float(config.get("video", {}).get("duration_seconds", 60)) - 2
        if duration <= 0:
            raise ValueError("Durée de démonstration trop courte.")
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\x00\x00" * int(duration * 24000))
        LOGGER.warning("Démonstration : piste silencieuse, aucune voix générée.")
    elif provider == "elevenlabs":
        from .elevenlabs import synthesize_elevenlabs
        return synthesize_elevenlabs(text, output, config)
    elif provider == "system":
        _system(text, output, speech)
    elif provider == "espeak":
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if not binary:
            raise RuntimeError("Installez espeak-ng pour la voix gratuite (Ubuntu : apt-get install espeak-ng), "
                               "ou configurez speech.provider=google et les identifiants Google Cloud.")
        subprocess.run([binary, "-v", str(speech.get("voice", "fr-fr")), "-s",
                        str(speech.get("rate", 155)), "-w", str(output), "--stdin"],
                       input=text, text=True, encoding="utf-8", check=True, timeout=120,
                       capture_output=True)
    elif provider == "google":
        if not speech.get("google_voice"):
            raise ValueError("speech.google_voice doit désigner une voix Cloud TTS disponible.")
        output.write_bytes(_google(text, speech))
    else:
        raise ValueError(f"Fournisseur vocal inconnu : {provider}")
    if not output.is_file() or output.stat().st_size < 44:
        raise RuntimeError("La synthèse n'a pas produit un fichier audio valide.")
    return output


def main() -> None:
    """Lance la synthèse seule sur un fichier de narration UTF-8."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    from .config import load_config
    synthesize(args.text.read_text(encoding="utf-8"), args.output,
               load_config(args.config))


if __name__ == "__main__":
    main()
