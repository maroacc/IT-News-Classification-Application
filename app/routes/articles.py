import logging
import math
from datetime import datetime, timezone
from typing import List

import feedparser
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.classifier import classifier, RECENCY_LAMBDA
from app.database import SessionLocal, get_db
from app.fetcher import FetcherService
from app.models import Article, RSSSourceModel
from app.schemas import ArticleFullResponse, ArticleIngest, ArticleResponse, SourceCreate

logger = logging.getLogger(__name__)

router = APIRouter()


def _compute_recency(published_at: datetime) -> float:
    """Exponential decay recency score — 1.0 at publication, 0.5 after 48h."""
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours_elapsed = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 3600)
    return math.exp(-RECENCY_LAMBDA * hours_elapsed)


def _with_scores(articles: List[Article]) -> List[dict]:
    """
    Enrich a list of Article ORM objects with freshly computed recency_score
    and final_score, then sort by final_score descending.
    """
    enriched = []
    for a in articles:
        recency = _compute_recency(a.published_at)
        final = (a.importance_score or 0.0) * recency
        enriched.append((final, recency, a))
    enriched.sort(key=lambda x: x[0], reverse=True)
    return enriched


@router.get("/health")
def health():
    """Returns the model loading status. 'loading' until the ML model is ready, then 'ready'."""
    return {"status": "ready" if classifier.is_ready else "loading"}


@router.post("/ingest", status_code=200)
def ingest(articles: List[ArticleIngest], db: Session = Depends(get_db)):
    """
    Accept a batch of raw articles, classify each one, and persist to the database.
    Returns an acknowledgment with the count of articles received.
    """
    logger.info(f"[/ingest] Received batch of {len(articles)} articles")
    for article in articles:
        classifier.classify_and_save(article, db)
    logger.info(f"[/ingest] Batch processed successfully")
    return {"status": "ok", "received": len(articles)}


@router.get("/retrieve", response_model=List[ArticleResponse])
def retrieve(db: Session = Depends(get_db)):
    """
    Return all filtered articles sorted by final_score descending.
    final_score = importance_score × recency_score, computed fresh at request time.
    Response matches the API contract shape exactly (id, source, title, body, published_at).
    """
    articles = db.query(Article).filter(Article.is_filtered == True).all()
    sorted_articles = [a for _, _, a in _with_scores(articles)]
    logger.info(f"[/retrieve] Returning {len(sorted_articles)} filtered articles")
    return sorted_articles


@router.post("/fetch")
def trigger_fetch():
    """Trigger an immediate fetch and classification of all RSS sources. Blocks until complete."""
    FetcherService()._fetch_all(SessionLocal, classifier)
    return {"status": "ok"}


@router.get("/articles", response_model=List[ArticleFullResponse])
def articles_full(db: Session = Depends(get_db)):
    """
    Return all filtered articles with full classification fields for the UI.
    recency_score and final_score are computed fresh at request time and injected into the response.
    """
    articles = db.query(Article).filter(Article.is_filtered == True).all()
    result = []
    for final, recency, a in _with_scores(articles):
        result.append(ArticleFullResponse(
            id=a.id,
            source=a.source,
            title=a.title,
            body=a.body,
            published_at=a.published_at,
            url=a.url,
            importance_score=a.importance_score,
            recency_score=recency,
            final_score=final,
            category=a.category,
            ingested_at=a.ingested_at,
        ))
    logger.info(f"[/articles] Returning {len(result)} articles with full detail")
    return result


@router.post("/sources", status_code=201)
def add_source(payload: SourceCreate, db: Session = Depends(get_db)):
    # Duplicate check
    if db.query(RSSSourceModel).filter(RSSSourceModel.feed_url == payload.feed_url).first():
        raise HTTPException(status_code=409, detail="This feed URL is already registered.")

    # Validate by fetching
    feed = feedparser.parse(payload.feed_url)
    if not feed.entries:
        raise HTTPException(status_code=422,
            detail="No articles found at that URL. Please verify the RSS feed URL.")

    # Save
    source = RSSSourceModel(name=payload.name, feed_url=payload.feed_url)
    db.add(source)
    db.commit()
    logger.info(f"[/sources] Added new source '{payload.name}' ({payload.feed_url})")
    return {"status": "ok", "name": source.name}
