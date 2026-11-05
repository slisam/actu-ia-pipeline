# Démarrage sur Windows

Cette installation utilise Gemini API au niveau gratuit, avec jusqu'à quatre clés de secours. Le montage et la voix fonctionnent localement. Les clés API et les comptes de publication demandent une configuration initiale. Un quota Gemini atteint met l'application en pause ; aucune rotation de comptes ne prolonge ce quota.

## 1. Préparer les outils

Installez [Python 3.11 ou plus récent](https://www.python.org/downloads/windows/). Pendant l'installation de Python, activez son ajout au `PATH`. Ouvrez ensuite PowerShell dans le dossier du projet.

```powershell
.\scripts\setup.ps1
```

Le script crée `.venv` et installe les bibliothèques Python. Ajouter ensuite au moins une clé dans `.env` et confirmer le projet au niveau Free dans `config.yaml`, selon [API_KEYS.md](API_KEYS.md). Une connexion dans une fenêtre automatisée n'est pas nécessaire.

Si Windows bloque les scripts locaux, lancez cette commande pour cette seule exécution :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

Le niveau gratuit de l'API est indépendant de votre abonnement AI Pro. Le diagnostic ne peut pas vérifier la facturation distante : utiliser un projet au niveau Free sans facturation payante activée.

## 2. Vérifier puis produire

```powershell
.\.venv\Scripts\python.exe -m pipelineia doctor
.\.venv\Scripts\python.exe -m pipelineia demo
.\.venv\Scripts\python.exe -m pipelineia run
```

Le diagnostic signale les éléments manquants. La démonstration et la production utilisent une voix française Windows installée, par exemple Microsoft Hortense. L'option `demo --silent` crée une démonstration silencieuse. Si aucune voix française n'est disponible, ajoutez le français et ses fonctions vocales dans les paramètres **Heure et langue** de Windows, puis relancez le diagnostic.

La commande `run` produit les fichiers sans publier. Pour publier aussi sur les plateformes activées et connectées dans `config.yaml` :

```powershell
.\.venv\Scripts\python.exe -m pipelineia run --publish
```

Consultez les instructions de publication du projet pour connecter vos comptes. Les clés restent dans `.env`, ignoré par Git. Les compteurs et délais de reprise sont enregistrés dans la base locale ignorée par Git.

## 3. Activer l'exécution quotidienne

Une fois les clés API configurées, un premier essai réussi et les destinations de publication connectées :

```powershell
.\scripts\install-task.ps1 -Time '19:00'
```

Cela crée la tâche Windows **PipelineIA-Actualites-Quotidien**, sous votre compte courant, qui lance `run --publish` depuis le dossier du projet chaque jour. L'heure est configurable au format `HH:mm`. Le script vérifie que le fuseau Windows correspond à Paris ; l'heure suit alors les changements saisonniers habituels.

Le PC doit être allumé, connecté à Internet et votre session Windows doit rester ouverte. L'écran peut être verrouillé. Si une exécution est manquée, Windows essaie de la lancer quand la session est à nouveau disponible ; il ne lance pas deux productions simultanément. Une clé révoquée ou un quota épuisé peut interrompre un épisode. Cette solution locale ne garantit pas une exécution lorsque le PC est arrêté.

Pour modifier l'heure, relancez le script avec la nouvelle heure. Pour retirer uniquement cette tâche :

```powershell
.\scripts\install-task.ps1 -Uninstall
```

Le retrait conserve les vidéos, la configuration et les connexions. Déplacer le dossier du projet nécessite de retirer la tâche depuis son ancien emplacement, puis de la recréer depuis le nouveau. Les scripts fournis ne sont pas exécutés automatiquement à la simple ouverture du dépôt.

## Client Gemini CLI facultatif

Le client officiel reste disponible comme fournisseur alternatif, mais l'essai réel du 5 novembre 2026 a été refusé par Google avec `UNSUPPORTED_CLIENT` pour le compte connecté. La connexion du navigateur automatisé a aussi été refusée. Ces voies restent expérimentales ; l'API est le fournisseur par défaut.

Pour préparer volontairement cette alternative, installez [Node.js LTS 22 ou plus récent](https://nodejs.org/) puis lancez :

```powershell
.\scripts\setup.ps1 -Provider gemini_cli -InstallGemini -Login
```

L'installation utilise le paquet officiel `@google/gemini-cli`. Choisissez **Sign in with Google**, utilisez le compte concerné, puis quittez avec `/quit`. Cette commande ne change pas le fournisseur de `config.yaml` ; un changement de fournisseur doit y être explicite. La documentation officielle indique actuellement Node.js 20 minimum ; ce projet retient Node.js 22 ou plus récent. Sources : [installation officielle](https://geminicli.com/docs/get-started/installation/) et [connexion Google](https://geminicli.com/docs/get-started/authentication/).
