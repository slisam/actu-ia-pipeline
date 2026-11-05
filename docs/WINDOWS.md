# Démarrage sur Windows

Cette installation utilise Gemini dans un profil Microsoft Edge séparé pour travailler avec votre compte Google AI Pro. Aucun abonnement supplémentaire n'est nécessaire pour le montage et la voix locale. Le compte Google doit être connecté une première fois ; les comptes de publication demandent également une autorisation initiale. Le pipeline ne connecte pas automatiquement vos trois comptes et ne change pas de compte pour contourner un quota.

## 1. Préparer les outils

Installez [Python 3.11 ou plus récent](https://www.python.org/downloads/windows/). Microsoft Edge doit être disponible sur votre PC. Pendant l'installation de Python, activez son ajout au `PATH`. Ouvrez ensuite PowerShell dans le dossier du projet.

```powershell
.\scripts\setup.ps1 -Login
```

Le script crée `.venv` et installe les bibliothèques Python, dont Playwright pour piloter le navigateur. L'option `-Login` ouvre Gemini dans un profil Edge dédié : connectez le compte de votre abonnement Google AI Pro et suivez les instructions du terminal. Votre profil Edge habituel reste indépendant. La session du profil dédié reste sur le PC et est exclue de Git.

Si Windows bloque les scripts locaux, lancez cette commande pour cette seule exécution :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Login
```

Le navigateur utilise la session Gemini et les limites disponibles pour le compte connecté. Il ne convertit pas l'abonnement en crédits d'API. Une reconnexion, un contrôle Google ou un changement de l'interface peuvent nécessiter une intervention. Aucun passage à une API payante n'est déclenché automatiquement.

## 2. Vérifier puis produire

```powershell
.\.venv\Scripts\python.exe -m pipelineia doctor
.\.venv\Scripts\python.exe -m pipelineia demo
.\.venv\Scripts\python.exe -m pipelineia run
```

Le diagnostic signale les éléments manquants. La démonstration utilise une piste silencieuse marquée comme telle ; la production normale utilise une voix française Windows installée, par exemple Microsoft Hortense. Si aucune voix française n'est disponible, ajoutez le français et ses fonctions vocales dans les paramètres **Heure et langue** de Windows, puis relancez le diagnostic.

La commande `run` produit les fichiers sans publier. Pour publier aussi sur les plateformes activées et connectées dans `config.yaml` :

```powershell
.\.venv\Scripts\python.exe -m pipelineia run --publish
```

Consultez les instructions de publication du projet pour connecter vos comptes. Les fichiers de configuration et journaux restent dans le dossier du projet. Le profil Gemini est conservé localement dans le dossier indiqué par `browser.profile_dir` de `config.yaml`.

## 3. Activer l'exécution quotidienne

Une fois la connexion Google et un premier essai réussis :

```powershell
.\scripts\install-task.ps1 -Time '19:00'
```

Cela crée la tâche Windows **PipelineIA-Actualites-Quotidien**, sous votre compte courant, qui lance `run --publish` depuis le dossier du projet chaque jour. L'heure est configurable au format `HH:mm`. Le script vérifie que le fuseau Windows correspond à Paris ; l'heure suit alors les changements saisonniers habituels.

Le PC doit être allumé, connecté à Internet et votre session Windows doit rester ouverte. L'écran peut être verrouillé. Si une exécution est manquée, Windows essaie de la lancer quand la session est à nouveau disponible ; il ne lance pas deux productions simultanément. Une reconnexion Google peut parfois être nécessaire. Cette solution locale ne garantit pas une exécution lorsque le PC est arrêté.

Pour modifier l'heure, relancez le script avec la nouvelle heure. Pour retirer uniquement cette tâche :

```powershell
.\scripts\install-task.ps1 -Uninstall
```

Le retrait conserve les vidéos, la configuration et les connexions. Déplacer le dossier du projet nécessite de retirer la tâche depuis son ancien emplacement, puis de la recréer depuis le nouveau. Les scripts fournis ne sont pas exécutés automatiquement à la simple ouverture du dépôt.

## Client Gemini CLI facultatif

Le client officiel reste disponible comme fournisseur alternatif, mais l'essai réel du 5 novembre 2026 a été refusé par Google avec `UNSUPPORTED_CLIENT` pour le compte connecté. Son fonctionnement avec votre abonnement n'est donc pas garanti. Le fournisseur navigateur est celui configuré par défaut.

Pour préparer volontairement cette alternative, installez [Node.js LTS 22 ou plus récent](https://nodejs.org/) puis lancez :

```powershell
.\scripts\setup.ps1 -Provider gemini_cli -InstallGemini -Login
```

L'installation utilise le paquet officiel `@google/gemini-cli`. Choisissez **Sign in with Google**, utilisez le compte concerné, puis quittez avec `/quit`. Cette commande ne change pas le fournisseur de `config.yaml` ; un changement de fournisseur doit y être explicite. La documentation officielle indique actuellement Node.js 20 minimum ; ce projet retient Node.js 22 ou plus récent. Sources : [installation officielle](https://geminicli.com/docs/get-started/installation/) et [connexion Google](https://geminicli.com/docs/get-started/authentication/).
