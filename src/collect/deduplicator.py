"""Déduplication d'articles par URL et similarité de titre."""
from __future__ import annotations

from rapidfuzz.fuzz import ratio


def _normalize_title(title: str) -> str:
    return " ".join(title.lower().split())


def deduplicate_articles(articles, threshold: float = 88.0):
    """Supprime les doublons (même URL ou titres très proches), en gardant le premier."""
    result = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    for article in articles:
        url = article.url.rstrip("/").lower()
        title = _normalize_title(article.title)
        if url in seen_urls:
            continue
        if any(ratio(title, old) >= threshold for old in seen_titles):
            continue
        seen_urls.add(url)
        seen_titles.append(title)
        result.append(article)
    return result
