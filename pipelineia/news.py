"""Collecte bornée d'actualités récentes auprès de sources explicites."""

from __future__ import annotations

import calendar
import hashlib
import ipaddress
import logging
import socket
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)
TRACKERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def canonical_url(url: str) -> str:
    """Normalise une URL et retire seulement les paramètres de suivi connus."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host += f":{parts.port}"
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parts.query)
                             if not key.lower().startswith("utm_") and key.lower() not in TRACKERS))
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/") or "/", query, ""))


def _public_url(url: str, allowed_hosts: set[str]) -> None:
    """Refuse protocoles locaux, identifiants, hôtes inconnus et adresses privées."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if (parts.scheme not in {"https", "http"} or not host or parts.username or parts.password
            or parts.port not in {None, 80, 443}):
        raise ValueError("URL HTTP publique attendue")
    if not any(host == item or host.endswith("." + item) for item in allowed_hosts):
        raise ValueError(f"Domaine absent des sources autorisées : {host}")
    addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Les adresses locales ou privées sont interdites")


def _download(url: str, allowed_hosts: set[str], max_bytes: int, timeout: int) -> tuple[bytes, str]:
    """Télécharge avec limite de taille et contrôle de chaque redirection."""
    current = url
    for _ in range(5):
        _public_url(current, allowed_hosts)
        response = None
        for attempt in range(2):
            try:
                response = requests.get(current, timeout=(min(timeout, 10), timeout), stream=True,
                                        allow_redirects=False,
                                        headers={"User-Agent": "Pipelineia/2.0 (RSS news reader)"})
                if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                    response.close()
                    time.sleep(1)
                    continue
                break
            except (requests.Timeout, requests.ConnectionError):
                if attempt:
                    raise
                time.sleep(1)
        assert response is not None
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                current = urljoin(current, response.headers.get("Location", ""))
                continue
            response.raise_for_status()
            length = int(response.headers.get("Content-Length", "0"))
            if length > max_bytes:
                raise ValueError("Réponse trop volumineuse")
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError("Réponse trop volumineuse")
            return bytes(content), current
        finally:
            response.close()
    raise ValueError("Trop de redirections")


def _article_text(content: bytes) -> str:
    """Extrait le contenu principal et retire navigation, scripts et formulaires."""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [tag.get_text(" ", strip=True) for tag in main.find_all(["h1", "h2", "h3", "p", "li"])]
    text = "\n".join(paragraphs) if paragraphs else main.get_text(" ", strip=True)
    return " ".join(text.split())


def collect_news(config: dict, used_urls: set[str] | None = None) -> list[dict]:
    """Renvoie des articles frais, datés et dédupliqués, ou une liste vide."""
    settings = config.get("news", {})
    sources = config.get("sources", [])
    allowed_hosts = {(urlsplit(item["url"]).hostname or "").lower().removeprefix("www.")
                     for item in sources}
    allowed_hosts.update(str(host).lower().removeprefix("www.")
                         for host in settings.get("allowed_domains", []))
    now = datetime.now(timezone.utc)
    oldest = now - timedelta(hours=float(settings.get("max_age_hours", 48)))
    used = {canonical_url(url) for url in (used_urls or set())}
    timeout = max(1, min(30, int(settings.get("timeout_seconds", 15))))
    max_articles = max(1, min(20, int(settings.get("max_articles", 8))))
    max_bytes = max(10000, min(5_000_000, int(settings.get("max_bytes", 3_000_000))))
    min_chars = max(100, int(settings.get("min_article_chars", 200)))
    candidates: dict[str, dict] = {}
    for source in sources:
        try:
            data, _ = _download(source["url"], allowed_hosts, max_bytes, timeout)
            feed = feedparser.parse(data)
            for entry in feed.entries[:100]:
                stamp = entry.get("published_parsed") or entry.get("updated_parsed")
                if not stamp or not entry.get("link") or not entry.get("title"):
                    continue
                published = datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc)
                if published < oldest or published > now + timedelta(minutes=5):
                    continue
                url = canonical_url(urljoin(source["url"], entry.link))
                if url in used:
                    continue
                _public_url(url, allowed_hosts)
                candidates.setdefault(url, {"id": hashlib.sha256(url.encode()).hexdigest()[:16],
                                            "title": BeautifulSoup(entry.title, "html.parser").get_text(" ", strip=True),
                                            "url": url, "published_at": published.isoformat(),
                                            "source": source["name"]})
        except (requests.RequestException, OSError, ValueError, KeyError) as exc:
            LOGGER.warning("Source indisponible %s (%s)", source.get("name", "?"), type(exc).__name__)
    results: list[dict] = []
    ordered = sorted(candidates.values(), key=lambda item: item["published_at"], reverse=True)
    for article in ordered[:max_articles * 3]:
        try:
            content, final_url = _download(article["url"], allowed_hosts, max_bytes, timeout)
            url = canonical_url(final_url)
            if url in used or any(item["url"] == url for item in results):
                continue
            text = _article_text(content)
            if len(text) < min_chars:
                continue
            article.update(url=url, id=hashlib.sha256(url.encode()).hexdigest()[:16],
                           text=text[:int(settings.get("max_article_chars", 14000))])
            results.append(article)
            if len(results) == max_articles:
                break
        except (requests.RequestException, OSError, ValueError) as exc:
            LOGGER.warning("Article ignoré %s (%s)", article["title"][:60], type(exc).__name__)
    return results
