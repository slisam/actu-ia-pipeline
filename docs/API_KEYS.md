# Connecter les clés gratuites Gemini

Le fournisseur par défaut est maintenant `api_pool`. Il utilise l'API officielle, sans fenêtre de navigateur et sans dépendre de la connexion Gemini CLI qui a été refusée pendant les essais.

## Les quatre clés

Ouvrir [Google AI Studio — clés API](https://aistudio.google.com/api-keys) dans votre navigateur habituel. Utiliser vos comptes existants et un projet autorisé pour votre application. **Une seule clé fonctionnelle suffit pour commencer** ; les trois autres sont facultatives.

Dans la page Projects d'AI Studio, vérifier que le projet affiche le niveau **Free** et que sa facturation payante n'est pas activée. Vérifier aussi que le modèle choisi est disponible gratuitement pour ce projet et votre région. Ne pas activer la facturation pour ce parcours gratuit.

Reporter les clés uniquement dans le fichier `.env` local, jamais dans GitHub ou dans le chat :

```dotenv
GEMINI_API_KEY_1=
GEMINI_API_KEY_2=
GEMINI_API_KEY_3=
GEMINI_API_KEY_4=
```

Dans `config.yaml`, pour chaque clé renseignée :

1. Remplacer `quota_group` par l'identifiant réel de son projet Google Cloud. Deux clés du même projet doivent porter le même identifiant.
2. Passer `free_tier_confirmed` à `true` après la vérification du niveau Free. Laisser les autres emplacements à `false`.

Ce drapeau enregistre votre vérification ; il ne peut pas bloquer une facturation activée ultérieurement dans Google Cloud. Le code ne crée aucun compte de facturation, ne recharge aucun crédit et ne sélectionne aucun modèle payant de secours.

## Ce que fait la bascule

- Une clé invalide, révoquée ou non autorisée est écartée ; une autre clé configurée peut être essayée dans le plafond global.
- Un problème réseau peut donner lieu à un essai sur une autre clé, sans boucle illimitée.
- **Un quota atteint (HTTP429) déclenche immédiatement l'essai d'une clé d'un autre projet disponible.** Le projet concerné et toutes ses clés sont mis en pause jusqu'au délai annoncé par Google. Une limite quotidienne reconnue attend le prochain renouvellement de ce projet. Les appels suivants, y compris la vérification du script, ignorent les projets encore en pause.
- Les compteurs et délais sont enregistrés dans SQLite et survivent aux redémarrages. Les quotas journaliers locaux utilisent `America/Los_Angeles`, comme le renouvellement RPD de Gemini.
- Les quatre clés partagent le plafond applicatif `llm.daily_request_limit` : 12 tentatives réseau par jour par défaut. Ce plafond prudent est un choix local, pas le quota gratuit garanti par Google.

Les limites officielles s'appliquent **au projet, pas à la clé**. Pour que la bascule sur quota soit utile, les clés doivent appartenir à des projets différents disposant de leur propre quota. Le pipeline ne crée aucun compte ni projet et n'augmente aucun quota distant. Si tous les projets sont indisponibles, ou si un plafond local est atteint, il s'arrête. [Limites Gemini](https://ai.google.dev/gemini-api/docs/rate-limits).

## Vérifier et démarrer

Depuis le dossier du projet :

```powershell
.\.venv\Scripts\python.exe -m pipelineia doctor
.\.venv\Scripts\python.exe -m pipelineia run
```

`doctor` n'envoie aucun prompt : il vérifie la présence locale des réglages sans afficher les clés. `run` consomme de vrais appels uniquement si une clé est renseignée et son niveau gratuit confirmé. La rédaction puis le contrôle éditorial utilisent normalement deux appels réussis ; des corrections ou incidents peuvent en demander davantage. Le budget d'un épisode est borné à quatre générations et huit tentatives réseau par défaut.

La planification quotidienne reste séparée de la connexion API et de la publication. Il faut connecter les comptes sociaux avant d'exécuter `run --publish` ou d'installer la tâche de publication.

[Facturation Gemini](https://ai.google.dev/gemini-api/docs/billing), [tarifs et modèles gratuits](https://ai.google.dev/gemini-api/docs/pricing). L'abonnement personnel Google AI Pro et le niveau de facturation de l'API sont deux mécanismes différents.
