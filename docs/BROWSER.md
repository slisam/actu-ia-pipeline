# Mode navigateur expérimental

Les essais de connexion Google dans Edge et Chrome automatisés ont été refusés. Ce mode n'est plus le défaut et ne constitue pas une voie de production validée. Utiliser [l'API gratuite](API_KEYS.md) pour le parcours courant ; les instructions ci-dessous restent une référence pour un environnement où la connexion serait autorisée.

Le mode choisi par défaut utilise **Gemini Web et le compte Google connecté**, pour rédiger et vérifier les scripts avec l'abonnement existant. Il ne facture pas une API Gemini en arrière-plan et ne génère pas de clips Veo. Le montage et la voix restent locaux. Les limites du forfait et la disponibilité de Gemini continuent de s'appliquer.

Le mode est fourni comme intégration locale : son fonctionnement avec votre compte ne sera établi qu'après une connexion et un essai réels. Les tests du projet simulent les réponses ; ils ne prouvent pas que Google autorise la connexion automatisée à votre compte. Google peut demander une connexion manuelle ou modifier son interface. Le pipeline s'arrête en cas de blocage, de quota ou de réponse invalide, sans changer de compte ni basculer vers une API payante.

## Première connexion

Dans le dossier du projet, sous Windows :

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pipelineia.browser login --config config.yaml
```

Connectez vous-même le compte souhaité dans la fenêtre dédiée, terminez les éventuelles vérifications Google, puis revenez au terminal et appuyez sur Entrée lorsque le champ de message Gemini est visible. La commande de connexion n'envoie aucun prompt et ne consomme pas volontairement de génération.

Le profil persistant est conservé sous `data/google-browser/`, exclu de Git. Il contient une session sensible : ne le partagez pas et ne l'ajoutez jamais à GitHub. Ce profil est distinct du profil Chrome/Edge habituel ; aucune copie de cookies ou d'identifiants n'est effectuée. Fermez sa fenêtre avant de lancer le pipeline. Un verrou évite deux utilisations simultanées.

## Configuration

```yaml
llm:
  provider: gemini_browser
  max_requests_per_run: 4
browser:
  profile_dir: data/google-browser
  channel: msedge
  headless: false
  timeout_seconds: 180
  stable_seconds: 4
```

Utilisez `chrome` si Google Chrome est installé. Pour Chromium, installez le navigateur puis choisissez `channel: chromium` :

```powershell
.venv\Scripts\python.exe -m playwright install chromium
```

Le navigateur reste visible par défaut pour rendre les connexions et blocages compréhensibles. Un ordinateur doit rester allumé et disposer d'une session utilisateur ouverte pour ce mode visible. GitHub Actions ne récupère pas la connexion locale.

Chaque demande ouvre une nouvelle discussion, remplit le champ de message et attend un objet JSON stable après la fin de génération. L'intégration lit seulement le contenu affiché ; elle n'utilise pas d'API privée ou de jetons extraits. Elle conserve les mêmes contrôles du script et la même vérification séparée que les autres fournisseurs.

## Limites connues

- Une session Google révoquée ou expirée demande de relancer la commande de connexion.
- Une CAPTCHA ou une vérification de sécurité demande une intervention manuelle ; aucun contournement n'est prévu.
- Une modification des éléments de la page Gemini peut demander une adaptation du code.
- Le modèle effectif est celui sélectionné dans Gemini Web. Ce mode ne prétend pas forcer un modèle API ou regrouper les quotas de trois comptes.
- Un quota de l'application ne garantit ni un nombre fixe de vidéos ni une disponibilité permanente.

[Limites officielles de Gemini](https://support.google.com/gemini/answer/16275805?hl=fr), [documentation Playwright sur les profils persistants](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).
