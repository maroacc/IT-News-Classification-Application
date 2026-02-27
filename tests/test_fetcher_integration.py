"""
Integration tests for the fetcher — these make real HTTP calls to RSS feeds.
Run them with:  pytest tests/test_fetcher_integration.py -v
Or via marker: pytest -m integration -v
"""
import re
from datetime import datetime, timezone

import pytest

from app.fetcher import (
    ArsTechnicaSource,
    HackerNewsSource,
    RedditSysadminSource,
    SOURCES,
    TomsHardwareSource,
)

pytestmark = pytest.mark.integration  # marks every test in this file as integration


def assert_valid_articles(articles, source_name: str):
    """Shared assertions for all source integration tests."""

    # Feed must return at least one article
    assert len(articles) > 0, f"[{source_name}] No articles returned — feed may be down"

    for article in articles:
        # Required fields must be present and non-empty
        assert article.id, f"[{source_name}] Article missing id"
        assert article.title, f"[{source_name}] Article missing title"
        assert article.source == source_name, f"[{source_name}] Unexpected source value: {article.source}"

        # published_at must be a valid UTC datetime
        assert isinstance(article.published_at, datetime), \
            f"[{source_name}] published_at is not a datetime"
        assert article.published_at.tzinfo == timezone.utc, \
            f"[{source_name}] published_at is not UTC"

        # Body, if present, must not contain HTML tags
        if article.body:
            assert not re.search(r"<[^>]+>", article.body), \
                f"[{source_name}] Body contains HTML tags: {article.body[:100]}"


class TestRedditSysadminLive:
    def test_fetches_real_articles(self):
        articles = RedditSysadminSource().fetch()
        assert_valid_articles(articles, "reddit-sysadmin")


class TestArsTechnicaLive:
    def test_fetches_real_articles(self):
        articles = ArsTechnicaSource().fetch()
        assert_valid_articles(articles, "ars-technica")


class TestHackerNewsLive:
    def test_fetches_real_articles(self):
        articles = HackerNewsSource().fetch()
        assert_valid_articles(articles, "the-hacker-news")


class TestTomsHardwareLive:
    def test_fetches_real_articles(self):
        articles = TomsHardwareSource().fetch()
        assert_valid_articles(articles, "toms-hardware")


class TestAllSourcesLive:
    def test_all_registered_sources_return_articles(self):
        """Smoke test — verifies every source in the registry is reachable."""
        for source in SOURCES:
            articles = source.fetch()
            assert len(articles) > 0, \
                f"Source '{source.source_name}' returned no articles — feed may be down or URL changed"