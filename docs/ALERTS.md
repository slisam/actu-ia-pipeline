# Alertes d'échec Telegram

Les alertes couvrent la collecte, la rédaction Gemini, les quotas, la voix ElevenLabs, le montage et la publication. Une publication partielle indique la destination concernée. Un résultat distant incertain demande de vérifier l'historique avant un nouvel envoi.

Les messages utilisent des textes prédéfinis, l'identifiant quotidien de l'épisode, l'étape et la plateforme. Les scripts, clés, jetons, corps d'erreurs et chemins locaux ne sont pas envoyés. Aucun service de génération n'est utilisé pour écrire une alerte.

## Connecter le bot

1. Dans Telegram, créer un bot dédié à Pipelineia avec [BotFather](https://t.me/BotFather), puis copier son jeton.
2. Ouvrir une conversation privée avec ce bot et lui envoyer `/start` vous-même.
3. Renseigner `TELEGRAM_BOT_TOKEN` uniquement dans `.env` local.
4. Depuis le dossier du projet, chercher l'identifiant de la conversation :

```powershell
.\.venv\Scripts\python.exe -m pipelineia alerts-chat
```

Cette commande lit les mises à jour du bot sans envoyer de message ni afficher son jeton ou le contenu des échanges. Avec un bot dédié, vous devez reconnaître votre conversation privée. Ne pas sélectionner l'identifiant d'une autre personne. Un bot utilisé ailleurs avec un webhook peut nécessiter un bot distinct.

5. Copier l'identifiant positif affiché dans `TELEGRAM_CHAT_ID`, puis vérifier et envoyer un test :

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

```powershell
.\.venv\Scripts\python.exe -m pipelineia doctor
.\.venv\Scripts\python.exe -m pipelineia alerts-test
```

`doctor` ne contacte pas Telegram. `alerts-test` envoie un message réel à la conversation configurée, sans produire de vidéo. Les groupes, canaux et identifiants `@...` ne sont pas pris en charge : cette intégration cible une conversation privée positive.

[API officielle](https://core.telegram.org/bots/api#sendmessage), [lecture des mises à jour](https://core.telegram.org/bots/api#getupdates).

## Journal et doublons

Les incidents et la file d'envoi restent dans la base privée `data/state.sqlite3`. Un incident est regroupé par épisode, étape, catégorie et plateforme. Les répétitions augmentent son compteur local. Par défaut, un nouvel échec encore présent après une heure peut rappeler un incident déjà envoyé.

Une erreur de notification ne remplace jamais l'erreur du pipeline. Sans identifiants Telegram, l'incident reste en attente localement. Une panne du canal est enregistrée avec un code fixe. Un quota Telegram annonce un délai respecté, avec au maximum trois tentatives. Une livraison possiblement réussie mais non confirmée est marquée `uncertain` et n'est pas répétée automatiquement.

Quand l'épisode réussit, les incidents sont résolus et les alertes encore en attente sont annulées. Aucune notification de succès n'est envoyée. Une journée sans actualité récente exploitable n'est pas un échec ; l'indisponibilité de toutes les sources en est un. Une bascule Gemini réussie après un quota ne produit pas d'alerte.

Un traitement encore en cours sur une plateforme attend quinze minutes avant notification. S'il réussit avant l'envoi, l'alerte en attente est annulée. Les commandes `doctor` et `demo` ne déclenchent pas d'alertes d'échec.

## Relance des notifications

Cette commande traite seulement les alertes dont le délai est écoulé et affiche les compteurs de la file ; elle ne relance pas la production :

```powershell
.\.venv\Scripts\python.exe -m pipelineia alerts-flush
```

Sous Windows, `scripts/install-task.ps1` prépare maintenant la production quotidienne et la tâche `PipelineIA-Alertes`, qui lance la purge toutes les cinq minutes. Pour installer seulement la purge :

```powershell
.\scripts\install-alert-task.ps1
```

Une notification différée ou une reprise attend une nouvelle purge : ce n'est pas un minuteur hébergé par Telegram. Le PC doit rester allumé et la session ouverte. Pour un serveur Linux, ajouter par exemple :

```cron
*/5 * * * * cd /chemin/actu-ia-pipeline && .venv/bin/python -m pipelineia alerts-flush
```

`install-task.ps1 -Uninstall` retire les deux tâches de ce dossier. `install-alert-task.ps1 -Uninstall` retire uniquement celle des alertes.

## Réglages et limites

`alerts` dans config.yaml choisit l'activation, le délai entre rappels, l'attente de publication, les tentatives et le délai réseau. `alerts.enabled: false` coupe l'enregistrement et les envois automatiques. Aucun message réel n'a été envoyé pendant les tests de développement.

Ce système ne peut pas détecter lui-même un ordinateur éteint, un processus qui ne démarre pas ou une configuration illisible avant le chargement du canal. Une surveillance externe serait nécessaire. Les livraisons `failed` ou `uncertain` restent dans le journal et les compteurs ; il n'y a pas de garantie absolue de réception.
