"""CLI du module de collecte, avec déduplication persistante SQLite."""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from src.common.config import charger_config, dossier_episode
from src.common.db import DB_PATH, ajouter_article, article_existe, connexion
from src.common.logging_setup import configurer_logging

from .deduplicator import deduplicate_articles
from .fetchers import Article, fetch_source
from .selector import select_articles

LOGGER = logging.getLogger(__name__)


def _args():
    parser = argparse.ArgumentParser(description="Collecte les actualités IA")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def _published_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _within_max_age(article: Article, max_age_hours: float) -> bool:
    """Un article sans date exploitable est conservé (ancienneté inconnue)."""
    published = _published_datetime(article.published_at)
    if published is None:
        return True
    return (datetime.now(timezone.utc) - published).total_seconds() <= max_age_hours * 3600


def _demo_articles() -> list[Article]:
    return [
        Article(
            "Démo : actualité IA",
            "https://example.com/demo-ia",
            "dry-run",
            "Article de démonstration IA",
            datetime.now(timezone.utc).isoformat(),
        )
    ]


def run(config, dry_run=False, limit=15, output_dir=None, db_path=None):
    collect = config.get("collect", {})
    sources = collect.get("sources", [])
    keywords = collect.get("keywords", [])
    max_age = float(collect.get("max_age_hours", 48))
    minimum = float(collect.get("minimum_score", 10))
    per_source = min(limit, int(collect.get("max_articles_per_source", limit)))

    all_articles: list[Article] = []
    failed_sources: list[dict[str, str]] = []

    if dry_run:
        all_articles = _demo_articles()
    else:
        for source in sources:
            name = source.get("name", "?")
            try:
                all_articles.extend(fetch_source(source, per_source))
            except Exception as exc:  # une source en échec ne bloque pas les autres
                failed_sources.append({"name": name, "error": str(exc)})
                LOGGER.error("Source %s échouée : %s", name, exc)

    fresh = [a for a in all_articles if _within_max_age(a, max_age)]
    unique = deduplicate_articles(fresh)

    if dry_run:
        selected = select_articles(unique, keywords, limit, minimum)
    else:
        with connexion(db_path or DB_PATH) as conn:
            # Filtrer les URLs déjà connues AVANT d'appliquer la limite,
            # sinon des doublons occupent des places et la sélection est réduite.
            new_articles = [a for a in unique if not article_existe(conn, a.url)]
            LOGGER.info("%d doublon(s) SQLite ignoré(s)", len(unique) - len(new_articles))
            selected = select_articles(new_articles, keywords, limit, minimum)
            for a in selected:
                ajouter_article(conn, a.url, a.title, a.source, a.summary, a.published_at or "")

    target = output_dir or dossier_episode(datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "articles": [a.to_dict() for a in selected],
        "failed_sources": failed_sources,
        "summary": {
            "collected": len(all_articles),
            "selected": len(selected),
            "failed_sources": len(failed_sources),
            "dry_run": dry_run,
        },
    }
    output_file = target / "collect.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info(
        "Collecte : %d article(s), %d source(s) en échec ; sortie %s",
        len(selected),
        len(failed_sources),
        output_file,
    )
    return selected


def main():
    args = _args()
    configurer_logging("collect")
    run(charger_config(args.config), args.dry_run, max(1, args.limit), args.output)


if __name__ == "__main__":
    main()
