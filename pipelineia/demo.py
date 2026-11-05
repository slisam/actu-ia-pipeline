"""Exemple hors ligne ; ne représente aucune actualité réelle."""


def demo_script() -> dict:
    """Fournit une narration de démonstration, explicitement non publiable."""
    hook = "Une minute suffit pour comprendre une annonce IA. Encore faut-il vérifier ce qu'elle promet."
    texts = [
        hook + " Voici une démonstration du format Actu IA, sans information d'actualité réelle.",
        "Le pipeline commence par consulter des sources officielles récentes. Il écarte les articles trop anciens et conserve un lien vers l'annonce originale. Si aucune source exploitable n'est trouvée, il s'arrête.",
        "Ensuite, il prépare une accroche et explique les faits en français. Chaque passage doit s'appuyer sur un extrait de la source. Une seconde vérification cherche les affirmations non justifiées.",
        "La voix est produite sur l'ordinateur. Le montage ajoute des cartes animées, des sous-titres et la référence de la source. La même narration devient une vidéo verticale, carrée ou horizontale.",
        "Enfin, les fichiers sont exportés. Les comptes autorisés peuvent recevoir les vidéos automatiquement. Cet exemple reste une démonstration : il ne sera jamais publié par le pipeline.",
    ]
    labels = ["DÉMONSTRATION • PAS UNE ACTUALITÉ", "01 • Trouver une source fiable", "02 • Expliquer et vérifier", "03 • Voix et montage local", "04 • Exporter dans les bons formats"]
    return {"title": "Actu IA • démonstration du format", "hook": hook, "language": "fr", "demo": True,
            "scenes": [{"narration": t, "on_screen": label, "source_ids": ["demo"]} for t, label in zip(texts, labels)],
            "sources": [{"id": "demo", "title": "Démonstration locale — aucune actualité réelle", "url": "https://example.com"}]}
