"""Collecte normalisée des actualités IA."""
from .deduplicator import deduplicate_articles
from .fetchers import Article, fetch_source
from .selector import score_article, select_articles

__all__ = [
    "Article",
    "deduplicate_articles",
    "fetch_source",
    "score_article",
    "select_articles",
]
