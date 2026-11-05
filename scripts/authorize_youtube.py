"""Autorisation YouTube initiale : navigateur local, puis fichier OAuth privé."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


def main() -> None:
    """Enregistre un jeton renouvelable hors des journaux et du dépôt."""
    parser = argparse.ArgumentParser(description="Autoriser une fois le compte YouTube propriétaire.")
    parser.add_argument("--client-secrets", type=Path, required=True,
                        help="Fichier OAuth de type application de bureau téléchargé de Google Cloud.")
    parser.add_argument("--output", type=Path, default=Path("data/youtube-credentials.secret.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Le fichier de sortie existe déjà ; choisir un autre nom.")
    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secrets),
               scopes=["https://www.googleapis.com/auth/youtube.upload"])
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise SystemExit("Google n'a pas fourni de refresh_token ; vérifier l'autorisation OAuth.")
    values = {"YOUTUBE_CLIENT_ID": credentials.client_id,
              "YOUTUBE_CLIENT_SECRET": credentials.client_secret,
              "YOUTUBE_REFRESH_TOKEN": credentials.refresh_token}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(values, indent=2), encoding="utf-8")
    try:
        args.output.chmod(0o600)
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.info("Autorisation enregistrée dans %s. Copier les trois valeurs dans les secrets du déploiement ; ne jamais committer ce fichier.", args.output)


if __name__ == "__main__":
    main()
