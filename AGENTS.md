# AGENTS.md — Règles du projet "Actu IA Pipeline"

## Objectif
Pipeline Python qui produit des vidéos YouTube/TikTok/Instagram sur l'actualité IA/tech, en français.
Flux : collecte → sélection → script → voix (ElevenLabs) → visuels → montage → publication.
Chaque vidéo passe par une VALIDATION HUMAINE avant publication.

## Stack
Python 3.11+, venv, requirements.txt · LLM : `google-genai` (Gemini) · Voix : ElevenLabs (timestamps)
Visuels : Playwright, Pexels, Gemini images · Montage : FFmpeg + MoviePy · Stockage : SQLite + output/
Publication : YouTube Data API v3 · Orchestration : n8n (appelle les CLI)

## Règles obligatoires
1. Aucune clé API dans le code : tout via .env (python-dotenv). .env dans .gitignore. Maintenir .env.example.
2. Noms de modèles (Gemini, voix ElevenLabs) dans config.yaml, jamais en dur.
3. Prompts LLM dans prompts/*.md, jamais en dur.
4. Chaque module est indépendant, a sa propre CLI et est testable seul.
5. Les modules communiquent via des JSON dans output/<id_episode>/.
6. Logging via `logging` (fichier logs/ + console), pas de print().
7. Retry avec backoff exponentiel (tenacity) sur les appels API, messages d'erreur clairs.
8. Type hints et docstrings en français.
9. Tests pytest pour chaque module (API mockées).
10. JAMAIS de publication publique automatique : "private" ou "scheduled" uniquement.
11. Avant de coder un module : présenter un plan. Après : expliquer comment le tester (commande concrète).

## Utilisateur
Non expert : expliquer simplement, donner les commandes exactes, prévenir avant toute action risquée
(suppression de fichiers, publication, dépense d'API).
