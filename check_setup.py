#!/usr/bin/env python3
"""
Script de vérification de l'installation et configuration du pipeline.

Vérifie :
1. Présence de toutes les clés API dans .env
2. Présence des dépendances principales
3. Connectivité à Gemini (test minimal)
4. Accès aux fichiers de configuration

Usage:
    python check_setup.py
"""

import sys
from pathlib import Path

# Couleurs pour la console
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"


def print_check(status: bool, message: str):
    """Affiche un message de vérification avec statut."""
    symbol = f"{Colors.GREEN}✓{Colors.RESET}" if status else f"{Colors.RED}✗{Colors.RESET}"
    print(f"{symbol} {message}")
    return status


def check_env_variables() -> bool:
    """Vérifie la présence des variables d'environnement essentielles."""
    print(f"\n{Colors.BLUE}1. Vérification des variables d'environnement{Colors.RESET}")

    from dotenv import load_dotenv
    import os

    env_path = Path(".env")
    if not env_path.exists():
        print_check(False, ".env introuvable")
        print(f"  {Colors.YELLOW}→ Copie .env.example en .env et remplis les valeurs{Colors.RESET}")
        return False

    load_dotenv(".env")

    required_vars = [
        "GEMINI_API_KEY",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_VOICE_ID",
        "PEXELS_API_KEY",
        "YOUTUBE_CLIENT_SECRETS_FILE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]

    all_present = True
    for var in required_vars:
        value = os.getenv(var)
        if value and value != f"your_{var.lower()}_here" and not value.startswith("your_"):
            print_check(True, f"{var}: OK")
        else:
            print_check(False, f"{var}: manquante ou vide")
            all_present = False

    return all_present


def check_dependencies() -> bool:
    """Vérifie la présence des dépendances principales."""
    print(f"\n{Colors.BLUE}2. Vérification des dépendances Python{Colors.RESET}")

    dependencies = [
        ("google-genai", "google.generativeai"),
        ("python-dotenv", "dotenv"),
        ("pyyaml", "yaml"),
        ("feedparser", "feedparser"),
        ("trafilatura", "trafilatura"),
        ("requests", "requests"),
        ("tenacity", "tenacity"),
        ("playwright", "playwright"),
        ("moviepy", "moviepy"),
        ("pillow", "PIL"),
        ("google-api-python-client", "googleapiclient"),
        ("pytest", "pytest"),
        ("rich", "rich"),
    ]

    all_present = True
    for pkg_name, import_name in dependencies:
        try:
            __import__(import_name)
            print_check(True, f"{pkg_name}")
        except ImportError:
            print_check(False, f"{pkg_name} (manquante)")
            all_present = False

    if not all_present:
        print(f"  {Colors.YELLOW}→ Exécute : pip install -r requirements.txt{Colors.RESET}")

    return all_present


def check_files() -> bool:
    """Vérifie la présence des fichiers de configuration."""
    print(f"\n{Colors.BLUE}3. Vérification des fichiers de configuration{Colors.RESET}")

    files = [
        "config.yaml",
        ".env.example",
        "requirements.txt",
        "prompts",
        "src/common",
    ]

    all_present = True
    for file_path in files:
        p = Path(file_path)
        exists = p.exists()
        print_check(exists, f"{file_path}")
        if not exists:
            all_present = False

    return all_present


def check_gemini_connectivity() -> bool:
    """Teste la connectivité à Gemini avec un appel minimal."""
    print(f"\n{Colors.BLUE}4. Test de connectivité Gemini{Colors.RESET}")

    try:
        import os
        from dotenv import load_dotenv
        import google.generativeai as genai

        load_dotenv(".env")
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key or api_key.startswith("your_"):
            print_check(False, "GEMINI_API_KEY non configurée")
            return False

        genai.configure(api_key=api_key)
        client = genai.Client()

        # Appel minimal (test de connectivité)
        response = client.models.generate_content(
            model="models/gemini-1.5-flash",
            contents="Réponds avec un seul mot : test",
        )

        if response.text:
            print_check(True, f"Réponse reçue : '{response.text.strip()}'")
            return True
        else:
            print_check(False, "Réponse vide de Gemini")
            return False

    except Exception as e:
        print_check(False, f"Erreur Gemini : {e}")
        print(f"  {Colors.YELLOW}→ Vérifie ta clé API et ta connexion réseau{Colors.RESET}")
        return False


def check_ffmpeg() -> bool:
    """Vérifie la présence de FFmpeg."""
    print(f"\n{Colors.BLUE}5. Vérification de FFmpeg{Colors.RESET}")

    import shutil

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print_check(True, f"FFmpeg trouvé : {ffmpeg_path}")
        return True
    else:
        print_check(False, "FFmpeg non trouvé")
        print(f"  {Colors.YELLOW}→ Installation :{Colors.RESET}")
        print(f"     macOS: brew install ffmpeg")
        print(f"     Ubuntu: sudo apt install ffmpeg")
        print(f"     Windows: winget install ffmpeg")
        return False


def main():
    """Exécute toutes les vérifications."""
    print(f"\n{Colors.BLUE}{'='*60}")
    print("  Vérification de la configuration - Actu IA Pipeline")
    print(f"{'='*60}{Colors.RESET}\n")

    checks = [
        ("Variables d'environnement", check_env_variables),
        ("Dépendances Python", check_dependencies),
        ("Fichiers de configuration", check_files),
        ("Connectivité Gemini", check_gemini_connectivity),
        ("FFmpeg", check_ffmpeg),
    ]

    results = []
    for name, check_func in checks:
        try:
            results.append((name, check_func()))
        except Exception as e:
            print_check(False, f"{name}: {e}")
            results.append((name, False))

    # Résumé
    print(f"\n{Colors.BLUE}{'='*60}")
    print("  Résumé")
    print(f"{'='*60}{Colors.RESET}\n")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status_symbol = f"{Colors.GREEN}✓{Colors.RESET}" if result else f"{Colors.RED}✗{Colors.RESET}"
        print(f"{status_symbol} {name}")

    print(f"\n{passed}/{total} vérifications réussies\n")

    if passed == total:
        print(f"{Colors.GREEN}✓ Tout est prêt ! Tu peux lancer le pipeline.{Colors.RESET}\n")
        return 0
    else:
        print(f"{Colors.RED}✗ Certaines vérifications ont échoué.{Colors.RESET}")
        print(f"{Colors.YELLOW}→ Corriges les erreurs ci-dessus et réexécute ce script.{Colors.RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
