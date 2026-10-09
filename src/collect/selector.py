"""Classement des articles selon les mots-clés de config.yaml."""
from __future__ import annotations

import re

from .fetchers import Article


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    # Correspondance sur mot entier : « IA » ne doit pas matcher « via » ou « média »,
    # ni « AI » matcher « said ».
    return re.compile(rf"(?<!\w){re.escape(keyword.lower())}(?!\w)")


def score_article(article: Article, keywords) -> float:
    title = article.title.lower()
    text = f"{title} {article.summary.lower()}"
    patterns = [_keyword_pattern(k) for k in keywords if k.strip()]
    hits = sum(1 for p in patterns if p.search(text))
    title_hits = sum(1 for p in patterns if p.search(title))
    return min(100.0, round(hits * 12.0 + title_hits * 18.0, 2))


def select_articles(articles, keywords, limit: int = 15, minimum_score: float = 0.0):
    selected = []
    for article in articles:
        article.score = score_article(article, keywords)
        if article.score >= minimum_score:
            selected.append(article)
    # Score décroissant, puis article le plus récent d'abord (tri stable).
    selected.sort(key=lambda a: a.published_at or "", reverse=True)
    selected.sort(key=lambda a: a.score, reverse=True)
    return selected[:limit]
