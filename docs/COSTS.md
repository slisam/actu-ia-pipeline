# Coûts, comptes Google et publication

## Recommandation

Pour une minute d'actualité IA, le choix le plus économique est un montage de cartes animées originales, une voix française de synthèse et des sous-titres. Le même épisode est décliné aux différents formats. Générer chaque seconde avec un modèle vidéo coûte beaucoup plus cher et n'aide pas à vérifier les faits.

La chaîne conseillée est : flux RSS officiels → sélection d'un sujet récent → script sourcé avec hook → contrôle éditorial → voix locale SAPI sous Windows ou eSpeak NG sous Linux → montage FFmpeg → exports et publication vers les comptes connectés. Le calcul peut fonctionner sur un ordinateur déjà disponible ou sur un serveur. Le prix de cette machine et son électricité restent à prendre en compte.

Le fournisseur textuel choisi par défaut est **Gemini Web dans un navigateur dédié**, pour utiliser le compte et l'abonnement existants. Une première connexion manuelle est obligatoire, puis la session locale est conservée. Le fonctionnement réel du compte dans cette intégration doit encore être validé après connexion ; les tests simulés ne prouvent pas cette disponibilité. Une session révoquée, un quota atteint, une vérification Google ou un changement d'interface peuvent interrompre le traitement. Voir [la procédure du navigateur](BROWSER.md).

**Gemini CLI reste une alternative officielle**, si le compte y est éligible : connexion Google initiale, puis réutilisation locale en mode headless. La documentation annonce 1 500 requêtes de modèle par jour pour AI Pro, avec limites et disponibilité variables. Un compte gratuit ou une licence non éligible peut être refusé ; cette intégration ne suppose pas que la connexion CLI déjà présente possède AI Pro. [Authentification officielle](https://geminicli.com/docs/get-started/authentication/), [mode headless officiel](https://geminicli.com/docs/cli/headless/), [quotas et tarification CLI](https://geminicli.com/docs/resources/quota-and-pricing/).

Ces deux modes produisent le texte, pas la voix ou les clips Veo. Le mode `gemini` via API est un choix explicite alternatif pour un hébergement serveur. Le pipeline ne bascule pas silencieusement du navigateur ou du CLI vers une API payante si un quota est atteint.

## Hypothèse de budget

**Avec les réglages par défaut : aucun coût API additionnel pour le texte, la voix ou les visuels**, tant que Gemini Web reste disponible dans les limites du forfait déjà payé. Le calcul, l'électricité, l'hébergement et les plateformes de publication éventuelles restent distincts. La voix locale est plus simple et moins naturelle qu'une bonne voix Cloud ; elle permet de commencer sans nouvelle facture.

Les tarifs API optionnels ci-dessous sont ceux affichés par les pages officielles consultées pour cette refonte ; ils doivent être revérifiés avant une montée en volume. Montants en dollars, hors taxes, abonnements existants, calcul, stockage et transfert. Ce sont des estimations, pas une garantie de facture.

| Poste | Tarif ou hypothèse | Exemple : 90 épisodes par mois |
| --- | --- | --- |
| Collecte RSS | Aucun service de recherche payant | 0 $ de redevance API |
| Texte Gemini Web, par défaut | Limites du compte et du forfait dans l'application | Aucun coût API distinct |
| Texte Gemini CLI avec Google OAuth, alternatif | Quota et éligibilité du compte | Aucun coût API distinct dans les quotas |
| Voix locale SAPI / eSpeak NG, par défaut | Synthèse sur la machine | Aucun service TTS facturé à l'usage |
| Gemini 3.1 Flash-Lite | 0,25 $/million de tokens d'entrée ; 1,50 $/million de sortie | Environ 0,61 $ pour 12 000 tokens d'entrée + 2 500 de sortie par épisode |
| Gemini 3.5 Flash-Lite | 0,30 $/million en entrée ; 2,50 $/million en sortie | Environ 0,89 $ avec la même hypothèse |
| Voix Standard ou WaveNet Google | 4 millions de caractères gratuits par mois ; puis 4 $/million | 90 000 caractères à 1 000 par épisode : dans le quota gratuit, si disponible sur le compte |
| Montage FFmpeg et cartes originales | Aucun coût d'API de génération visuelle | Coût du calcul uniquement |

Les nouvelles tentatives, vérifications et tokens de raisonnement consomment aussi des tokens. Avec cette hypothèse, une enveloppe de **1 à 3 $ par mois de génération textuelle** laisse de la marge pour plusieurs passes. Le volume réel est à mesurer après quelques épisodes. [Tarifs Gemini](https://aistudio.google.com/docs/pricing), [tarifs Text-to-Speech](https://cloud.google.com/text-to-speech/pricing).

L'API Gemini possède un niveau gratuit soumis à quotas et disponibilité. Il peut suffire à faible volume ; un abonnement AI Pro n'est pas nécessaire pour ce niveau. Cloud Text-to-Speech demande néanmoins d'activer la facturation et facture automatiquement les dépassements. Une alerte de budget Google Cloud n'est pas, à elle seule, un plafond bloquant.

Gemini 2.5 Flash-Lite est moins cher mais son accès est réservé aux utilisateurs ayant déjà utilisé les modèles 2.5 ; il ne constitue donc pas un bon défaut pour une nouvelle installation. Le modèle reste configurable pour les comptes éligibles. [Cycle de vie officiel](https://aistudio.google.com/docs/deprecations).

## Les trois comptes Google

Il faut distinguer **Google AI Pro personnel**, **Google Workspace professionnel** et **projet Google Cloud**. Trois comptes professionnels ne donnent pas automatiquement trois abonnements AI Pro ni trois avantages API.

Google annonce un avantage de **10 $ mensuels de crédits Google Cloud pour AI Pro**, via Google Developer Program. L'avantage doit être activé sur chaque compte personnel éligible et associé à un compte de facturation. Dans la page My Benefits, l'option « Always use this billing account » applique automatiquement les futurs crédits. Google indique que ces crédits peuvent servir à Gemini via AI Studio ou Vertex AI. [Annonce officielle](https://blog.google/innovation-and-ai/technology/developers-tools/gdp-premium-ai-pro-ultra/), [conditions et activation](https://developers.google.com/profile/help/benefits).

**Ne pas présumer que les trois crédits peuvent être cumulés en une réserve unique de 30 $.** L'éligibilité, les projets liés, les conditions d'attribution et les crédits effectivement visibles dans la facturation de chaque compte doivent être vérifiés. Les crédits Flow et les plafonds de l'application Gemini sont des mécanismes distincts des appels API.

Pour le mode par défaut, **un seul compte Google connecté au profil du navigateur suffit normalement**. Choisir le compte une fois et utiliser sa session locale, puis conserver les autres abonnements pour les usages qui en profitent réellement. Le CLI peut demander un projet Cloud pour certains comptes Workspace et certaines licences ; l'application Web possède ses propres conditions d'accès. Si le mode API optionnel est choisi, connecter explicitement un projet et vérifier son crédit et son budget. Il n'est pas nécessaire de faire tourner automatiquement trois identités pour ce volume. Changer de compte pour contourner un quota n'est pas une stratégie de production.

## Utiliser le navigateur et les abonnements existants

**Oui, piloter l'interface Gemini ou Flow depuis un navigateur peut utiliser l'accès du compte connecté.** Flow prend officiellement en charge les navigateurs Chromium et les abonnements Pro. Certains forfaits Workspace éligibles disposent aussi d'un accès Flow avec 50 crédits quotidiens. La quantité réellement disponible et le coût en crédits doivent être lus dans chaque compte. [Accès officiel à Flow](https://support.google.com/flow/answer/16353333?hl=fr).

Cela ne transforme pas le quota de l'application en quota API : les produits possèdent leurs propres limites et systèmes de crédits. Les limites de l'application Gemini dépendent du calcul et de l'usage ; Google les décrit avec des fenêtres de cinq heures et un plafond hebdomadaire. [Limites de l'application](https://support.google.com/gemini/answer/16275805?hl=fr), [crédits par produit](https://support.google.com/googleone/answer/16287445?hl=fr).

Un mode navigateur est donc une option pour profiter des abonnements déjà payés, surtout pour des inserts visuels. En revanche, le maintien de session, les vérifications de connexion, les changements d'interface, les temps de génération et la récupération des fichiers rendent son fonctionnement sans surveillance plus fragile qu'une API. C'est une appréciation technique, pas l'affirmation d'une interdiction générale par Google. Les documents consultés ne garantissent pas un accès automatisé illimité par navigateur. Il faut tester un compte connecté, conserver une reprise après erreur et s'arrêter lorsqu'un quota ou une vérification de connexion bloque la génération.

Le mode navigateur demande une session locale ou un navigateur persistant connecté ; un workflow GitHub Actions ne récupère pas automatiquement les sessions Google de l'ordinateur. C'est la voie retenue ici pour utiliser le compte existant. Gemini CLI avec authentification locale reste une alternative si le compte y est éligible ; l'API avec crédits Cloud activés est une alternative pour un serveur. Flow peut fournir des médias optionnels lorsque l'accès a été vérifié ; la génération de médias dans Flow ne fait pas partie de cette intégration Gemini textuelle.

## Pourquoi ne pas générer toute la minute avec Veo ?

À titre de comparaison, Google affiche Veo 3.1 Lite avec audio à **0,05 $ par seconde en 720p** et **0,08 $ en 1080p**. Soixante secondes représentent environ **3 $ ou 4,80 $**, avant variantes et nouvelles générations. À 90 épisodes, cela représente environ **270 à 432 $ de vidéo générée**. Les clips doivent être assemblés pour atteindre une minute. [Tarifs Google Cloud](https://cloud.google.com/model-garden/pricing), [présentation de Veo 3.1 Lite](https://blog.google/innovation-and-ai/technology/ai/veo-3-1-lite/).

Un insert généré occasionnel peut se justifier ; il n'est pas nécessaire au fonctionnement économique du pipeline.

## Hébergement et publication

GitHub Actions propose du calcul inclus selon le plan et la visibilité du dépôt. Les runners standards des dépôts publics sont gratuits ; les dépôts privés ont une allocation mensuelle. Le stockage des vidéos a ses propres limites. Conserver peu d'artefacts et mesurer la durée des rendus avant de conclure à un hébergement gratuit. Un ordinateur déjà allumé avec une tâche planifiée constitue aussi une option économique. [Facturation GitHub Actions](https://docs.github.com/en/actions/concepts/billing-and-usage).

| Plateforme | Ce qui peut être automatisé | Connexion ou limite externe |
| --- | --- | --- |
| YouTube / Shorts | Envoi et métadonnées via l'API officielle | Autorisation OAuth du compte, API activée et quota ; vérifier le statut retourné après l'envoi |
| Instagram Reels | Création d'un conteneur puis publication | Compte Business/Creator, permissions Meta et média accessible par l'API ; vérifier l'état du conteneur |
| TikTok | Export vidéo + texte ; publication via un service ou une intégration approuvée | L'API Direct Post demande une expérience de consentement et exclut les outils réservés aux comptes de sa propre équipe ; ne pas promettre un autopost interne sans intervention |

La documentation YouTube consultée précise que les projets API non vérifiés ne sont plus systématiquement limités au mode privé. L'API retourne néanmoins le statut effectif et les quotas du projet restent applicables. [YouTube videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert).

Instagram est réservé aux comptes professionnels pour cette fonction. [Collection officielle Meta](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api), [guide de publication Meta](https://developers.facebook.com/docs/instagram-platform/content-publishing).

TikTok impose le mode privé aux clients non audités et exige le consentement explicite avant l'envoi. La génération automatique et la publication automatique sont donc deux capacités distinctes. Un service déjà approuvé peut avoir un abonnement supplémentaire et doit être choisi selon ses possibilités réelles. [Règles TikTok Direct Post](https://developers.tiktok.com/docs/en/content-sharing-guidelines).

## Flux primaires vérifiés

Ces URL ont répondu en HTTP 200 et leur XML a été parsé pendant la refonte. Une indisponibilité future doit être traitée comme une erreur de source, jamais comme l'autorisation d'inventer une actualité.

| Source | Flux |
| --- | --- |
| OpenAI | https://openai.com/news/rss.xml |
| Google AI | https://blog.google/innovation-and-ai/technology/ai/rss/ |
| Google DeepMind | https://deepmind.google/blog/rss.xml |
| Hugging Face | https://huggingface.co/blog/feed.xml |
| Google Research | https://research.google/blog/rss/ |
| NVIDIA | https://blogs.nvidia.com/blog/category/deep-learning/feed/ |

Un flux officiel décrit ce que son éditeur annonce ; il ne prouve pas à lui seul une supériorité ou un résultat indépendant. Le script doit attribuer les annonces et conserver les liens et dates des sources. La présence d'un article ou d'une image dans un flux ne transfère pas ses droits de réutilisation : les cartes visuelles originales évitent d'avoir à recopier des médias pour produire une vidéo.
