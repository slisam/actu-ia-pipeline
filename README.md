# Pipelineia

Des actualités IA en français transformées en vidéos de **60 secondes** : accroche immédiate, explication sourcée, voix, sous-titres et trois formats. La refonte remplace l'ancien collecteur incomplet ; l'historique Git reste disponible.

## Le choix économique

**Par défaut, Gemini API au niveau gratuit, avec une voix et un montage locaux** :

1. Collecte des annonces récentes dans les flux officiels OpenAI, Google, DeepMind et Hugging Face.
2. Rédaction et vérification avec **Gemini API**, dans un projet au niveau gratuit confirmé.
3. Voix gratuite sur l'ordinateur : **Windows SAPI en français** ou eSpeak sur Linux.
4. Cartes graphiques originales, montage FFmpeg et sous-titres.
5. Exports **1080×1920**, **1080×1080** et **1920×1080**, puis publication sur les comptes configurés.

Une seule clé suffit pour démarrer ; quatre emplacements sont prévus. **Lorsqu'un quota est atteint, le pipeline essaie immédiatement une clé d'un autre projet disponible.** Les clés d'un même projet partagent leur pause jusqu'au délai de reprise Google. Les appels sont bornés par épisode et par jour, avec des compteurs persistants. Si aucun projet n'est disponible, l'épisode attend la reprise des quotas.

Les clés doivent appartenir à des projets au niveau gratuit, sans facturation payante activée. Le code n'active aucune facturation ; il ne peut cependant pas vérifier le statut distant du projet ni empêcher une facturation modifiée hors du pipeline. La voix et les cartes originales ne consomment aucune API. L'électricité, le calcul et l'hébergement restent à compter. [Connexion des clés](docs/API_KEYS.md) · [Coûts](docs/COSTS.md).

Le montage produit les vidéos à partir de cartes et de voix ; il ne génère pas de clips Veo et n'automatise pas Flow. Les anciens modes navigateur et Gemini CLI restent expérimentaux : les connexions réelles ont été refusées par Google lors des essais.

## Démarrer sous Windows

Python 3.11+ est nécessaire. Dans PowerShell, depuis le dossier du projet :

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pipelineia doctor
.\.venv\Scripts\python.exe -m pipelineia demo
.\.venv\Scripts\python.exe -m pipelineia run
```

Avant `doctor` et `run`, ajouter au moins une clé dans `.env` et renseigner son projet et sa confirmation du niveau Free dans `config.yaml`, selon [API_KEYS.md](docs/API_KEYS.md). Le diagnostic n'effectue aucun appel de génération. `demo` utilise un exemple explicitement fictif ; `run` recherche une vraie actualité. Les vidéos apparaissent dans `output/`.

Pour générer rapidement un exemple en basse résolution :

```powershell
.\.venv\Scripts\python.exe -m pipelineia demo --quick
```

## Chaque jour, automatiquement

Après connexion des destinations sociales et configuration de `publishing.platforms` :

```powershell
.\scripts\install-task.ps1 -Time '19:00'
```

La tâche produit puis publie à 19h, heure de Paris. Le PC doit être allumé, connecté et la session Windows ouverte. Le même script validé est repris après un incident ; une vidéo n'est pas envoyée deux fois sans vérifier son état. Les actualités périmées ne sont pas publiées lors des reprises.

Pour une machine disponible en permanence, utiliser Linux avec son planificateur ou le conteneur fourni. [Guide Windows](docs/WINDOWS.md) · [Exploitation et Docker](docs/OPERATIONS.md).

## Plateformes

| Destination | Sortie | Publication |
| --- | --- | --- |
| YouTube Shorts | Verticale, 60 s | API officielle, OAuth initial puis envoi autonome |
| Instagram Reels | Verticale, 60 s | Compte professionnel, connexion Meta et hébergement public du MP4 |
| TikTok | Verticale, 60 s + légende | **Export uniquement** ; le parcours Direct Post impose des contraintes de consentement |
| Autres usages | Carrée et horizontale | Fichiers MP4 exportés |

Le dépôt démarre avec **aucune destination sociale active**. Pour YouTube public, configurer `publishing.platforms: [youtube]` et `publishing.youtube.privacy: public`. Les comptes et leurs droits ne peuvent pas être connectés avec le seul accès GitHub. [Guide de connexion](docs/PUBLISHING.md).

## Fichiers produits

Chaque épisode quotidien utilise `output/AAAA-MM-JJ-actu-ia/` :

- `articles.json` : sources collectées, dates et textes utilisés.
- `script.json` : hook, scènes, preuves exactes et résultat du contrôle éditorial.
- `voice.wav`, `narration.txt` : voix et texte.
- `vertical.mp4`, `square.mp4`, `landscape.mp4` : exports de 60 secondes.
- `captions.srt`, `timing.json` : sous-titres et repères estimés.
- `manifest.json`, `publication.json` : empreintes des fichiers et états des publications.

Les sous-titres utilisent un minutage estimé, sans alignement phonétique. La voix locale est économique ; une voix Google Cloud peut être choisie explicitement dans `config.yaml` si sa qualité est préférable.

## Sources et reprises

Les articles sans date, trop anciens, déjà utilisés ou inaccessibles sont écartés. Aucun sujet exploitable signifie aucune vidéo. Un épisode traite une seule annonce ; ses affirmations sont contrôlées contre la source, avec une seconde passe de vérification. Ce contrôle automatique peut se tromper : les liens sont conservés et les cartes affichent l'origine de l'annonce.

Une base SQLite locale garde les scripts et les états de publication. **Elle contient des secrets de session : ne pas la committer ou l'envoyer dans un artefact.** En cas de réponse ambiguë d'une plateforme, le pipeline conserve l'état et ne republie pas aveuglément. Les logs tournants sont dans `logs/`.

## Réglages et tests

`config.yaml` choisit les sources, modèles, voix, formats et destinations. `.env.example` décrit les quatre emplacements de clés Gemini et les secrets sociaux optionnels. `llm.provider: api_pool` est le défaut ; les anciens fournisseurs restent optionnels. Google Cloud TTS (`speech.provider: google`) est une alternative explicite, jamais un repli automatique.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Les tests simulent les services externes et réalisent aussi un vrai montage de 60 secondes en basse résolution. GitHub Actions vérifie Windows et Linux et conserve une démonstration silencieuse pendant trois jours. La production quotidienne reste sur la machine où les comptes sont connectés.
