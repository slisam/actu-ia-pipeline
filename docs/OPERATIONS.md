# Exploitation

## Ordinateur Windows

Suivre [WINDOWS.md](WINDOWS.md) et [API_KEYS.md](API_KEYS.md). Les clés API sont conservées dans `.env` local. La tâche quotidienne utilise ce même utilisateur, ses fichiers locaux et le même dossier du projet. Le PC doit être allumé et la session disponible. Les clés et connexions sociales restent révocables.

## Serveur Linux déjà disponible

Cette variante serveur utilise le fournisseur `api_pool` par défaut. Configurer au moins une clé et son projet gratuit selon API_KEYS.md. Installer Python 3.11+, espeak-ng, FFmpeg et une police DejaVu, puis :

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m pipelineia doctor
.venv/bin/python -m pipelineia demo
```

Il n'y a pas de connexion navigateur automatisée dans ce parcours API. Planifier ensuite une exécution quotidienne avec le planificateur du serveur, dans le dossier du projet et sous le même utilisateur. Exemple cron à 19h, **si le fuseau du serveur est Europe/Paris** :

```cron
0 19 * * * cd /chemin/actu-ia-pipeline && .venv/bin/python -m pipelineia run --publish
```

Sans destination sociale connectée, retirer `--publish` pour produire uniquement les vidéos. Le verrou et la date d'épisode empêchent deux exécutions du même jour de créer deux publications identiques. Une exécution avec `--publish` reprend aussi les épisodes interrompus des jours précédents.

## Docker optionnel

Le Dockerfile contient Node, Python, FFmpeg et eSpeak. Il ne contient aucun identifiant.

```sh
cp .env.example .env
mkdir -p data output logs
docker compose build
docker compose run --rm pipelineia python -m pipelineia doctor
docker compose run --rm pipelineia python -m pipelineia demo
docker compose run --rm pipelineia python -m pipelineia run --publish
```

Sur Linux, les dossiers montés doivent être accessibles à l'utilisateur du conteneur (UID1000 par défaut). Configurer les clés dans `.env` et les projets gratuits dans config.yaml avant `doctor`. Cette variante Docker n'a pas été exécutée lors de la refonte sur Windows.

## État, reprise et erreurs

`data/state.sqlite3` conserve les scripts validés et les états de publication. **Cette base contient aussi des URL de session et des jetons : ne jamais la publier ni l'envoyer dans un artefact CI.** Sauvegarder ensemble `data/` et `output/` dans un emplacement privé. Garder les vidéos d'un épisode tant que sa publication n'est pas terminée. Le journal refuse une vidéo modifiée après le début de son envoi.

Un incident réseau après une publication peut laisser l'état `uncertain`. Le pipeline ne réenvoie pas aveuglément la vidéo : il tente une vérification à distance lorsque l'API le permet. Sinon, consulter la plateforme et la base avant une intervention. Ne jamais supprimer la base pour relancer une publication. Les épisodes dont les sources dépassent news.max_age_hours sont marqués expired ; leur publication est ignorée.

Les sous-titres utilisent les repères ElevenLabs vérifiés lorsqu'ils sont disponibles, adaptés au tempo du montage. Sinon, timing.json indique le minutage estimé. Conserver le cache vocal de l'épisode pour réutiliser l'audio sans nouvelle synthèse lors d'une reprise ; voir ELEVENLABS.md pour les réponses incertaines d'un appel facturable. Le rendu bloque les accélérations excessives et ne coupe pas la narration. La vérification par modèle réduit les inventions sans constituer une garantie de vérité.

Si aucune actualité récente exploitable n'est disponible, aucune vidéo n'est générée. Les fichiers sont sous `output/AAAA-MM-JJ-actu-ia/` ; les logs tournants sous `logs/`. `publication.json` décrit les résultats par destination. Les codes de sortie sont 0 en cas de succès ou absence de nouvelle actualité, 2 pour une publication incomplète, 1 pour une autre erreur.

GitHub Actions exécute seulement les tests et une démonstration silencieuse. La production utilise le planificateur local/serveur ; aucun navigateur Google connecté n'est exporté vers GitHub.
