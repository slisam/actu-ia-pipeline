# Connecter la publication

## YouTube Shorts

1. Créer un projet Google Cloud et activer YouTube Data API v3.
2. Configurer l'écran de consentement OAuth et créer un client de type application de bureau. Ajouter le compte comme utilisateur test si le projet reste en test.
3. Mettre le fichier client hors Git, puis exécuter :

```powershell
.\.venv\Scripts\python.exe scripts/authorize_youtube.py --client-secrets C:\chemin\client_secret.json
```

Le script écrit un fichier privé `data/youtube-credentials.secret.json`. Reporter ses trois champs dans `.env` (`YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`) sans les transmettre dans un chat. Le parcours doit être réalisé avec le compte de la chaîne visée. Les jetons d'une application OAuth externe en mode test peuvent expirer après sept jours ; stabiliser l'écran de consentement selon les règles Google pour une exploitation durable.

```yaml
publishing:
  platforms: [youtube]
  youtube:
    privacy: public
```

Le dépôt conserve `private` comme valeur initiale pour permettre un premier contrôle de la chaîne cible. `public` active la diffusion publique automatique ; `unlisted` est également pris en charge. La vidéo verticale de 60 secondes est envoyée avec son titre, ses sources et ses métadonnées. Le pipeline déclare la présence de contenu synthétique et que la vidéo n'est pas destinée aux enfants. Vérifier que ces choix correspondent à votre contenu et audience. [Référence YouTube](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert).

## Instagram Reels

Utiliser un compte professionnel Business ou Creator et une application Meta avec les permissions de publication nécessaires. La version implémentée utilise **Instagram Login** et `graph.instagram.com` ; ne pas utiliser un jeton Facebook Login à sa place. Renseigner `IG_USER_ID`, `IG_ACCESS_TOKEN` (jeton longue durée) et `MEDIA_BASE_URL` dans `.env`.

Instagram doit télécharger le MP4 depuis une URL publique HTTPS. Deux options :

- S3 compatible/Cloudflare R2 : `MEDIA_S3_BUCKET`, `MEDIA_S3_ENDPOINT`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. `MEDIA_BASE_URL` est le domaine public du bucket. L'objet est envoyé automatiquement dans `identifiant-episode/vertical.mp4`.
- Serveur existant : `MEDIA_UPLOAD_DIR` est un dossier que votre serveur publie sous `MEDIA_BASE_URL`. Le pipeline y copie le fichier. Le dossier local à lui seul ne crée pas un serveur public.

Ajouter `instagram` à `publishing.platforms`. Le pipeline crée un conteneur Reel, vérifie son traitement puis le publie. Il renouvelle le jeton longue durée lorsque cela est possible ; un jeton expiré ou révoqué nécessite une nouvelle connexion. La version Graph est configurable sous `publishing.instagram.api_version`. [Guide Meta](https://developers.facebook.com/docs/instagram-platform/content-publishing).

## TikTok

Ajouter `tiktok` à `publishing.platforms` crée un export local avec vidéo et légende. **Cela ne publie pas sur TikTok.** Les règles officielles Direct Post imposent une interface et un consentement par publication, et excluent les outils limités aux comptes internes de leur équipe. Pour une diffusion plus intégrée, choisir un partenaire approuvé et vérifier son parcours de consentement. Aucun contournement par cookies ou appels non documentés n'est inclus. [Règles TikTok](https://developers.tiktok.com/doc/content-sharing-guidelines/).

## Vérifier puis exécuter

```powershell
.\.venv\Scripts\python.exe -m pipelineia doctor
.\.venv\Scripts\python.exe -m pipelineia run --publish
```

Le diagnostic vérifie la présence des réglages ; il ne prétend pas vérifier les droits et l'identité des comptes distants. Les comptes sociaux et les crédits Google ne peuvent pas être connectés avec le seul accès au dépôt GitHub.
