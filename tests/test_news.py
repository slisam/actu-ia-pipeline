"""La collecte refuse les informations périmées, non datées et les URL locales."""

import socket
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from pipelineia import news


def _entry(url: str, date: datetime | None) -> str:
    stamp = f"<pubDate>{format_datetime(date)}</pubDate>" if date else ""
    return f"<item><title>Une annonce IA</title><link>{url}</link>{stamp}</item>"


def test_collect_keeps_fresh_news_deduplicates_and_skips_used(monkeypatch):
    now = datetime.now(timezone.utc)
    items = [_entry("https://news.example/new?utm_source=rss", now),
             _entry("https://news.example/new", now),
             _entry("https://news.example/used", now),
             _entry("https://news.example/old", now - timedelta(days=4)),
             _entry("https://news.example/future", now + timedelta(hours=1)),
             _entry("https://news.example/undated", None)]
    feed = ("<rss><channel>" + "".join(items) + "</channel></rss>").encode()
    html = ("<html><nav>Texte de navigation</nav><article><h1>Une annonce IA</h1><p>"
            + "Une source officielle décrit un nouveau modèle et ses limites. " * 10
            + "</p></article></html>").encode()
    requested = []

    def download(url, *_):
        requested.append(url)
        return (feed if url.endswith("rss.xml") else html), url

    monkeypatch.setattr(news, "_download", download)
    monkeypatch.setattr(news, "_public_url", lambda *_: None)
    result = news.collect_news({"sources": [{"name": "Laboratoire", "url": "https://news.example/rss.xml"}]},
                               {"https://news.example/used?utm_medium=test"})
    assert len(result) == 1
    assert result[0]["url"] == "https://news.example/new"
    assert result[0]["source"] == "Laboratoire"
    assert "navigation" not in result[0]["text"]
    assert requested == ["https://news.example/rss.xml", "https://news.example/new"]


def test_failing_sources_return_empty_never_invent_news(monkeypatch):
    def fail(*_):
        raise requests.Timeout("échec")
    monkeypatch.setattr(news, "_download", fail)
    assert news.collect_news({"sources": [{"name": "Source", "url": "https://news.example/rss"}]}) == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost/a", "https://attacker.example/a",
                                     "https://u:p@news.example/a", "https://news.example:8080/a"])
def test_public_url_blocks_unknown_or_non_http_urls(url):
    with pytest.raises(ValueError):
        news._public_url(url, {"news.example"})


def test_public_url_blocks_dns_resolving_to_private_address(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="privées"):
        news._public_url("https://news.example/a", {"news.example"})


def test_public_url_checks_domain_boundary(monkeypatch):
    with pytest.raises(ValueError, match="Domaine"):
        news._public_url("https://evilnews.example/a", {"news.example"})


def test_download_rechecks_redirect_target(monkeypatch):
    class Response:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/private"}
        def close(self):
            pass
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kw: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(requests, "get", lambda *_args, **_kw: Response())
    with pytest.raises(ValueError, match="Domaine"):
        news._download("https://news.example/rss", {"news.example"}, 10000, 5)


def test_canonical_url_keeps_semantic_query_and_removes_only_trackers():
    assert news.canonical_url("https://www.news.example/a/?id=42&utm_source=x&fbclid=y#top") == "https://news.example/a?id=42"
