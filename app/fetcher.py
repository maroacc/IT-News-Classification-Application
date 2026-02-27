import asyncio
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List

import feedparser
from sqlalchemy.orm import Session

from app.schemas import ArticleIngest

logger = logging.getLogger(__name__)

FETCH_INTERVAL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_html(text: str) -> str:
    """Remove HTML tags from a string, returning clean plain text."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def parse_date(entry) -> datetime:
    """
    Extract a UTC datetime from a feedparser entry.
    Falls back to the current time if no date is found.
    """
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Base source — subclass this to add a new source
# ---------------------------------------------------------------------------

class BaseSource(ABC):
    """
    Abstract base class for all news sources.
    To add a new source: subclass this, set source_name, and implement fetch().
    """
    source_name: str  # unique slug, e.g. "reddit-sysadmin"

    @abstractmethod
    def fetch(self) -> List[ArticleIngest]:
        """Fetch articles and return them as a list of ArticleIngest objects."""
        pass


# ---------------------------------------------------------------------------
# RSS source — shared fetch logic for all RSS-based sources
# ---------------------------------------------------------------------------

class RSSSource(BaseSource):
    """
    Reusable RSS fetcher. Subclasses only need to set source_name and feed_url.
    Handles parsing, HTML stripping, date extraction, and error logging.
    """
    feed_url: str

    def fetch(self) -> List[ArticleIngest]:
        try:
            feed = feedparser.parse(self.feed_url)  # fetches and parses the RSS feed into a structured object
            articles = []

            for entry in feed.entries:
                # Use the RSS GUID as the article ID; fall back to the link
                article_id = entry.get("id") or entry.get("link")
                if not article_id:
                    logger.warning(f"[{self.source_name}] Skipping entry with no ID or link")
                    continue

                # RSS body may be in 'summary' or nested inside 'content'
                raw_body = (
                    entry.get("summary")
                    or (entry.get("content") or [{}])[0].get("value")
                    or ""
                )

                articles.append(ArticleIngest(
                    id=article_id,
                    source=self.source_name,
                    title=entry.get("title", "").strip(),
                    body=strip_html(raw_body) or None,
                    published_at=parse_date(entry),
                ))

            logger.info(f"[{self.source_name}] Fetched {len(articles)} articles")
            return articles

        except Exception as e:
            # Log the error and return an empty list so other sources are unaffected
            logger.error(f"[{self.source_name}] Failed to fetch: {e}")
            return []


# ---------------------------------------------------------------------------
# Concrete sources — add new sources here
# ---------------------------------------------------------------------------

class RedditSysadminSource(RSSSource):
    source_name = "reddit-sysadmin"
    feed_url = "https://www.reddit.com/r/sysadmin.rss"


class ArsTechnicaSource(RSSSource):
    source_name = "ars-technica"
    feed_url = "https://feeds.arstechnica.com/arstechnica/technology-lab"


class HackerNewsSource(RSSSource):
    source_name = "the-hacker-news"
    feed_url = "https://feeds.feedburner.com/TheHackersNews"


class TomsHardwareSource(RSSSource):
    source_name = "toms-hardware"
    feed_url = "https://www.tomshardware.com/feeds/all"


# Registry of active sources — add or remove entries here to enable/disable sources
SOURCES: List[BaseSource] = [
    RedditSysadminSource(),
    ArsTechnicaSource(),
    HackerNewsSource(),
    TomsHardwareSource(),
]


# ---------------------------------------------------------------------------
# Fetcher service — background loop
# ---------------------------------------------------------------------------

class FetcherService:
    """
    Runs a continuous background loop that fetches all sources every N seconds,
    classifies each article, and persists the result to the database.
    """

    def __init__(self, interval_seconds: int = FETCH_INTERVAL_SECONDS):
        self.interval_seconds = interval_seconds

    async def run(self, db_factory, classifier):
        """
        Entry point for the background task.
        db_factory: callable that returns a new SQLAlchemy Session (e.g. SessionLocal)
        classifier: the ClassifierService instance used to score articles
        """
        logger.info("FetcherService started — fetching every %ds", self.interval_seconds)
        while True:
            self._fetch_all(db_factory, classifier)
            await asyncio.sleep(self.interval_seconds)

    def _fetch_all(self, db_factory, classifier):
        """Fetch from every registered source and persist classified results."""
        logger.info("Starting fetch cycle")

        for source in SOURCES:
            articles = source.fetch()  # errors are handled inside fetch()

            if not articles:
                continue

            db: Session = db_factory()
            try:
                for article in articles:
                    # Classify and save — overwrites existing article if ID already exists
                    classifier.classify_and_save(article, db)
            finally:
                db.close()

        logger.info("Fetch cycle complete")