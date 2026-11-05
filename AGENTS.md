# Pipelineia — règles du projet

L'utilisateur a autorisé la refonte et l'automatisation sans validation manuelle systématique.
Objectif : actualités IA sourcées en français, hook immédiat, vidéos de 60 secondes.

- Python 3.11+, modules indépendants dans pipelineia, configuration dans config.yaml.
- Coût minimal : Gemini dans un navigateur dédié connecté au compte Google, voix locale, Pillow/FFmpeg. CLI et API restent optionnels.
- Gemini API et voix Google Cloud restent des options explicites.
- Ne jamais enregistrer de clés, cookies, jetons OAuth ou bases de publication dans Git.
- Prompts dans prompts/*.md ; modèles et voix configurables.
- Sources primaires récentes, citations vérifiées, refus si preuve insuffisante.
- Une démo doit rester explicitement identifiée et ne peut jamais être publiée.
- Publication uniquement sur les plateformes configurées par l'utilisateur ; respecter leurs API et exigences de consentement.
- État persistant et verrou : aucune republication automatique après une réponse ambiguë.
- Logs sans secrets ; backoff pour les lectures réseau ; pas de répétition aveugle des mutations.
- Tests pytest avec API simulées et rendu réel en basse résolution.
- Documenter les connexions initiales et les limites d'une exécution autonome.
