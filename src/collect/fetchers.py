"""Récupérateurs RSS et APIs publiques pour les sources de collecte."""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests

from src.common.retry import retry_api

LOGGER = logging.getLogger(__name__)
USER_AGENT = "actu-ia-pipeline/1.0 (+https://github.com/slisam/actu-ia-pipeline)"
TIMEOUT = 20
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"


@dataclass(slots=True)
class Article:
    title: str
    url: str
    source: str
    summary: str = ""
    published_at: str | None = None
    score: float = 0.0
    guid: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["metadata"] = data["metadata"] or {}
        return data


def _date(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    return entry.get("published") or entry.get("updated")


@retry_api()
def fetch_rss(url, source, limit=15, session=None):
    response = (session or requests).get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    articles = []
    for entry in parsed.entries[:limit]:
        title = str(entry.get("title", "")).strip()
        link = str(entry.get("link", "")).strip()
        if title and link:
            articles.append(
                Article(
                    title,
                    link,
                    source,
                    str(entry.get("summary", "")),
                    _date(entry),
                    guid=str(entry.get("id", link)),
                )
            )
    return articles


@retry_api()
def fetch_hackernews(url, source="Hacker News", limit=15, min_score=0, session=None):
    client = session or requests
    headers = {"User-Agent": USER_AGENT}
    response = client.get(url, timeout=TIMEOUT, headers=headers)
    response.raise_for_status()
    ids = response.json()[: limit * 3]
    articles = []
    for story_id in ids:
        item_response = client.get(HN_ITEM_URL.format(story_id), timeout=TIMEOUT, headers=headers)
        item_response.raise_for_status()
        item = item_response.json()
        if item and item.get("type") == "story" and item.get("score", 0) >= min_score and item.get("url"):
            published = (
                datetime.fromtimestamp(item["time"], tz=timezone.utc).isoformat() if item.get("time") else None
            )
            score = item.get("score", 0)
            articles.append(
                Article(
                    item.get("title", ""),
                    item["url"],
                    source,
                    f"Score HN: {score}",
                    published,
                    guid=str(story_id),
                    metadata={"hn_score": score, "hn_id": story_id},
                )
            )
        if len(articles) >= limit:
            break
    return articles


@retry_api()
def fetch_producthunt(url, source="Product Hunt", limit=15, session=None):
    token = os.getenv("PRODUCT_HUNT_TOKEN", "").strip()
    if not token:
        LOGGER.warning("PRODUCT_HUNT_TOKEN absent : Product Hunt ignoré")
        return []
    query = "query { posts(first: 20, order: NEWEST) { edges { node { id name tagline url createdAt } } } }"
    response = (session or requests).post(
        url,
        json={"query": query},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    edges = response.json().get("data", {}).get("posts", {}).get("edges", [])
    articles = []
    for edge in edges[:limit]:
        node = edge.get("node")
        if node:
            articles.append(
                Article(node["name"], node["url"], source, node.get("tagline", ""), node.get("createdAt"), guid=str(node["id"]))
            )
    return articles


def fetch_arxiv(url, source="arXiv", limit=15, session=None):
    return fetch_rss(url, source, limit, session)


def fetch_source(config, limit=15, session=None):
    kind = str(config.get("type", "rss")).lower()
    kwargs = {"limit": limit, "session": session}
    if kind == "rss":
        return fetch_rss(config["url"], config.get("name", "RSS"), **kwargs)
    if kind in {"hackernews", "hn"}:
        return fetch_hackernews(
            config["url"], config.get("name", "Hacker News"), min_score=int(config.get("min_score", 0)), **kwargs
        )
    if kind in {"producthunt", "product_hunt"}:
        return fetch_producthunt(config["url"], config.get("name", "Product Hunt"), **kwargs)
    if kind == "arxiv":
        return fetch_arxiv(config["url"], config.get("name", "arXiv"), **kwargs)
    raise ValueError(f"Type de source inconnu : {kind}")
