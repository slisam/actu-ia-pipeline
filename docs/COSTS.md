# Coûts et quotas

## Choix retenu

La chaîne par défaut est : RSS officiels → Gemini API au niveau gratuit → contrôle éditorial → voix locale française → cartes originales et FFmpeg → exports de60 secondes. L'interface Flow n'est pas automatisée et aucun clip Veo n'est nécessaire.

La voix Windows SAPI ou Linux eSpeak et les cartes n'ont aucun coût d'API. Le calcul, l'électricité, le stockage et l'hébergement public nécessaire à Instagram restent à compter. Un ordinateur déjà disponible évite un nouvel abonnement de serveur.

## Gemini gratuit

Le modèle par défaut `gemini-3.1-flash-lite` affiche une entrée et une sortie gratuites dans le niveau Free sur la page de tarifs consultée. L'accès réel, les limites et la disponibilité du modèle dépendent du projet et de la région. Les quotas chiffrés doivent être vérifiés dans AI Studio ; aucun nombre d'épisodes gratuits n'est garanti. [Tarifs officiels](https://ai.google.dev/gemini-api/docs/pricing), [limites](https://ai.google.dev/gemini-api/docs/rate-limits).

Utiliser un projet au niveau Free sans facturation payante activée. La présence d'une clé ne prouve pas ce statut. Le drapeau local `free_tier_confirmed` enregistre la vérification du propriétaire : il ne constitue pas un contrôle distant ni un plafond monétaire Google. Le pipeline ne crée pas de facturation et ne recharge pas de crédits. [Facturation](https://ai.google.dev/gemini-api/docs/billing).

Pour cette utilisation interne de production vidéo, le pipeline utilise des articles publics et n'expose pas un client API aux spectateurs. Les conditions Google comportent des exigences particulières pour les clients API mis à disposition d'utilisateurs dans l'EEE, en Suisse et au Royaume-Uni ; les revoir si le projet devient une application destinée à des utilisateurs. [Conditions Gemini](https://ai.google.dev/gemini-api/terms).

## Quatre clés, sans multiplication des quotas

Quatre emplacements de clés sont disponibles ; une seule clé fonctionnelle suffit. Les limites officielles Gemini s'appliquent au **projet**, pas à la clé. Des clés du même projet partagent donc leurs limites. Les clés sont gardées uniquement dans `.env` local. [Procédure de connexion](API_KEYS.md).

La bascule intervient sur clé invalide, incident temporaire ou quota atteint. **Sur HTTP429, le pipeline met le projet concerné en pause puis essaie immédiatement une clé d'un autre projet disponible.** Les clés du même projet partagent cette pause. Le délai Google est respecté pour chaque projet ; une limite quotidienne reconnue attend son renouvellement. Aucun compte ou projet n'est créé automatiquement et aucun quota distant n'est augmenté. [Limites officielles](https://ai.google.dev/gemini-api/docs/rate-limits).

Les plafonds locaux par défaut sont :

| Plafond | Valeur | Portée |
| --- | --- | --- |
| Générations logiques | 4 | Ensemble rédaction, vérification et corrections d'un épisode |
| Tentatives HTTP | 8 | Même épisode, toutes clés confondues |
| Tentatives quotidiennes | 12 | Toute l'application et ses quatre clés |

Ces valeurs sont des choix de prudence, pas les quotas gratuits annoncés par Google. Les requêtes refusées sont aussi comptées localement. Les compteurs sont conservés dans SQLite ; le jour quota utilise `America/Los_Angeles`, correspondant au renouvellement RPD à minuit Pacific. La rédaction et le contrôle demandent normalement deux appels réussis, avec davantage d'appels possibles en cas de correction.

## Abonnements AI Pro et autres modes

Un abonnement personnel AI Pro et le niveau gratuit de l'API sont distincts. Trois ou quatre abonnements ne constituent pas une réserve unique de quota API. Google propose aussi des crédits Cloud via certains avantages Developer Program, à activer sous conditions ; ils ne sont pas nécessaires au parcours Free retenu ici. [Avantages Developer Program](https://developers.google.com/profile/help/benefits).

Les essais réels de connexion du navigateur automatisé ont été refusés par Google. L'essai Gemini CLI a été refusé avec `UNSUPPORTED_CLIENT`. Ces modes restent expérimentaux et ne sont plus le défaut.

À titre de comparaison, le niveau payant standard de Gemini 3.1 Flash-Lite affiche 0,25 $/million de tokens d'entrée texte et 1,50 $/million de sortie. Avec 12 000 tokens d'entrée et 2 500 de sortie par épisode, 90 épisodes représentent environ 0,61 $, avant corrections et raisonnement supplémentaires. Ce calcul illustre une alternative ; aucune activation du payant n'est incluse. [Tarifs](https://ai.google.dev/gemini-api/docs/pricing).

## Publication

YouTube nécessite une autorisation OAuth initiale et un quota API. Instagram demande un compte professionnel, les droits Meta et un MP4 accessible en HTTPS. Le stockage public, les transferts ou un serveur peuvent coûter de l'argent. TikTok reste un export local ; ses règles Direct Post exigent un parcours de consentement. [Connexion des plateformes](PUBLISHING.md).

GitHub Actions sert aux tests et à la démonstration silencieuse. La production quotidienne utilise le planificateur de l'ordinateur ou du serveur et ses fichiers d'état privés.
