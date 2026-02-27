import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.fetcher import (
    SOURCES,
    RedditSysadminSource,
    parse_date,
    strip_html,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockEntry:
    """Simulates a feedparser entry object with controlled field values."""

    def __init__(self, id, title, summary="", published_parsed=None, link=None, content=None):
        self._data = {
            "id": id,
            "link": link or id,
            "title": title,
            "summary": summary,
            "content": content,
        }
        self.published_parsed = published_parsed or time.gmtime()
        self.updated_parsed = None

    def get(self, key, default=""):
        return self._data.get(key, default)


def make_mock_feed(*entries):
    """Wraps a list of MockEntry objects in a mock feedparser feed."""
    feed = MagicMock()
    feed.entries = list(entries)
    return feed


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_removes_tags(self):
        assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_plain_text_unchanged(self):
        assert strip_html("Hello world") == "Hello world"

    def test_handles_empty_string(self):
        assert strip_html("") == ""

    def test_handles_none(self):
        assert strip_html(None) == ""

    def test_strips_nested_tags(self):
        assert strip_html("<div><span>text</span></div>") == "text"


# ---------------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_uses_published_parsed(self):
        entry = MockEntry(id="x", title="x")
        entry.published_parsed = time.strptime("2024-01-15", "%Y-%m-%d")
        result = parse_date(entry)
        assert result == datetime(2024, 1, 15, tzinfo=timezone.utc)

    def test_falls_back_to_updated_parsed(self):
        entry = MockEntry(id="x", title="x")
        entry.published_parsed = None
        entry.updated_parsed = time.strptime("2024-06-01", "%Y-%m-%d")
        result = parse_date(entry)
        assert result.year == 2024 and result.month == 6

    def test_falls_back_to_now_when_no_date(self):
        entry = MockEntry(id="x", title="x")
        entry.published_parsed = None
        entry.updated_parsed = None
        result = parse_date(entry)
        # Just verify we get a valid UTC datetime back
        assert isinstance(result, datetime)
        assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# RSSSource.fetch()
# ---------------------------------------------------------------------------

class TestRSSSourceFetch:
    def test_returns_articles_with_correct_fields(self):
        source = RedditSysadminSource()
        entry = MockEntry(id="https://example.com/1", title="AWS outage", summary="Details here")
        with patch("feedparser.parse", return_value=make_mock_feed(entry)):
            articles = source.fetch()

        assert len(articles) == 1
        assert articles[0].id == "https://example.com/1"
        assert articles[0].source == "reddit-sysadmin"
        assert articles[0].title == "AWS outage"
        assert articles[0].body == "Details here"

    def test_html_is_stripped_from_body(self):
        source = RedditSysadminSource()
        entry = MockEntry(id="x", title="x", summary="<p>Clean <b>text</b></p>")
        with patch("feedparser.parse", return_value=make_mock_feed(entry)):
            articles = source.fetch()

        assert articles[0].body == "Clean text"

    def test_body_is_none_when_empty(self):
        source = RedditSysadminSource()
        entry = MockEntry(id="x", title="x", summary="")
        with patch("feedparser.parse", return_value=make_mock_feed(entry)):
            articles = source.fetch()

        assert articles[0].body is None

    def test_skips_entry_with_no_id_or_link(self):
        source = RedditSysadminSource()
        entry = MockEntry(id=None, title="No ID article", link=None)
        with patch("feedparser.parse", return_value=make_mock_feed(entry)):
            articles = source.fetch()

        assert articles == []

    def test_returns_empty_list_on_fetch_error(self):
        source = RedditSysadminSource()
        with patch("feedparser.parse", side_effect=Exception("Network error")):
            articles = source.fetch()

        assert articles == []

    def test_multiple_entries_all_returned(self):
        source = RedditSysadminSource()
        entries = [MockEntry(id=f"https://example.com/{i}", title=f"Article {i}") for i in range(5)]
        with patch("feedparser.parse", return_value=make_mock_feed(*entries)):
            articles = source.fetch()

        assert len(articles) == 5


# ---------------------------------------------------------------------------
# SOURCES registry
# ---------------------------------------------------------------------------

class TestSourcesRegistry:
    def test_all_sources_have_name_and_url(self):
        for source in SOURCES:
            assert source.source_name, f"{type(source).__name__} missing source_name"
            assert source.feed_url, f"{type(source).__name__} missing feed_url"

    def test_source_names_are_unique(self):
        names = [s.source_name for s in SOURCES]
        assert len(names) == len(set(names)), "Duplicate source names detected"

    def test_expected_sources_are_registered(self):
        names = {s.source_name for s in SOURCES}
        assert "reddit-sysadmin" in names
        assert "ars-technica" in names
        assert "the-hacker-news" in names
        assert "toms-hardware" in names