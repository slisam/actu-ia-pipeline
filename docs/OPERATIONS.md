# Exploitation

## Ordinateur Windows

Suivre [WINDOWS.md](WINDOWS.md) et [BROWSER.md](BROWSER.md). Le profil navigateur dédié conserve la connexion Google localement. La tâche quotidienne utilise ce même utilisateur, ses fichiers locaux et le même dossier du projet. Le PC doit être allumé et la session disponible. Les connexions Google et sociales restent révocables ; une nouvelle autorisation peut être nécessaire.

## Serveur Linux déjà disponible

Cette variante serveur utilise l'API explicite ou Gemini CLI si le compte y est encore éligible. Le mode navigateur visible par défaut est destiné à un ordinateur avec session graphique. Avant le déploiement serveur, choisir `llm.provider: gemini` avec sa clé, ou `gemini_cli` avec un compte éligible dans config.yaml. Installer Python 3.11+, Node 22+, espeak-ng, FFmpeg et une police DejaVu, puis :

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install -g @google/gemini-cli@0.61.0
cp .env.example .env
gemini
.venv/bin/python -m pipelineia doctor
.venv/bin/python -m pipelineia demo
```

La première connexion Google CLI est interactive et son éligibilité doit être vérifiée : le test de la connexion enregistrée lors de la refonte a été refusé par Google comme client non pris en charge. L'option n'est donc pas garantie pour chaque compte. Planifier ensuite une exécution quotidienne avec le planificateur du serveur, dans le dossier du projet et sous le même utilisateur. Exemple cron à 19h, **si le fuseau du serveur est Europe/Paris** :

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
docker compose run --rm pipelineia gemini
docker compose run --rm pipelineia python -m pipelineia doctor
docker compose run --rm pipelineia python -m pipelineia demo
docker compose run --rm pipelineia python -m pipelineia run --publish
```

Sur Linux, les dossiers montés doivent être accessibles à l'utilisateur du conteneur (UID1000 par défaut). La connexion Google dans un conteneur peut nécessiter le parcours de connexion à distance proposé par Gemini CLI. Si ce parcours n'est pas disponible dans votre environnement, utiliser l'installation locale ou l'option API. Cette variante Docker n'a pas été exécutée lors de la refonte sur Windows.

## État, reprise et erreurs

`data/state.sqlite3` conserve les scripts validés et les états de publication. **Cette base contient aussi des URL de session et des jetons : ne jamais la publier ni l'envoyer dans un artefact CI.** Sauvegarder ensemble `data/` et `output/` dans un emplacement privé. Garder les vidéos d'un épisode tant que sa publication n'est pas terminée. Le journal refuse une vidéo modifiée après le début de son envoi.

Un incident réseau après une publication peut laisser l'état `uncertain`. Le pipeline ne réenvoie pas aveuglément la vidéo : il tente une vérification à distance lorsque l'API le permet. Sinon, consulter la plateforme et la base avant une intervention. Ne jamais supprimer la base pour relancer une publication. Les épisodes dont les sources dépassent news.max_age_hours sont marqués expired ; leur publication est ignorée.

Les sous-titres sont estimés à partir de la narration, sans alignement phonétique payant. Un changement de voix ou de script peut modifier le rythme ; le rendu bloque les accélérations excessives et ne coupe pas la narration. La vérification par modèle réduit les inventions sans constituer une garantie de vérité. Les annonces sont attribuées à leurs éditeurs et les sources restent exportées.

Si aucune actualité récente exploitable n'est disponible, aucune vidéo n'est générée. Les fichiers sont sous `output/AAAA-MM-JJ-actu-ia/` ; les logs tournants sous `logs/`. `publication.json` décrit les résultats par destination. Les codes de sortie sont 0 en cas de succès ou absence de nouvelle actualité, 2 pour une publication incomplète, 1 pour une autre erreur.

GitHub Actions exécute seulement les tests et une démonstration silencieuse. La production utilise le planificateur local/serveur ; aucun navigateur Google connecté n'est exporté vers GitHub.
