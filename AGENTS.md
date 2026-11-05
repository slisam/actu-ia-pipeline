# Pipelineia — règles du projet

L'utilisateur a autorisé la refonte et l'automatisation sans validation manuelle systématique.
Objectif : actualités IA sourcées en français, hook immédiat, vidéos de 60 secondes.

- Python 3.11+, modules indépendants dans pipelineia, configuration dans config.yaml.
- Fournisseurs par défaut : Gemini API au niveau gratuit pour la rédaction, ElevenLabs pour la voix off payante demandée par l'utilisateur, et Pillow/FFmpeg pour le montage. La voix locale reste optionnelle. Le navigateur et CLI restent expérimentaux après refus de connexion Google lors des essais.
- Réutiliser l'audio ElevenLabs déjà généré lors d'une reprise de montage ; ne pas répéter aveuglément un appel facturable dont l'issue est inconnue. Garder les clés et fichiers audio hors Git.
- À la demande explicite de l'utilisateur, un HTTP429 suspend le projet concerné puis déclenche immédiatement l'essai d'une clé d'un autre projet configuré. Les clés du même projet partagent leur pause ; les autres restent utilisables.
- Respecter les limites projet, les délais de reprise et un plafond global d'appels. La confirmation du niveau gratuit est locale et ne prouve pas le statut de facturation distant.
- Ne jamais enregistrer de clés, cookies, jetons OAuth ou bases de publication dans Git.
- Prompts dans prompts/*.md ; modèles et voix configurables.
- Sources primaires récentes, citations vérifiées, refus si preuve insuffisante.
- Une démo doit rester explicitement identifiée et ne peut jamais être publiée.
- Publication uniquement sur les plateformes configurées par l'utilisateur ; respecter leurs API et exigences de consentement.
- État persistant et verrou : aucune republication automatique après une réponse ambiguë.
- Logs sans secrets ; backoff pour les lectures réseau ; pas de répétition aveugle des mutations.
- Tests pytest avec API simulées et rendu réel en basse résolution.
- Documenter les connexions initiales et les limites d'une exécution autonome.
