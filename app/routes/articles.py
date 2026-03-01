import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.classifier import classifier
from app.database import SessionLocal, get_db
from app.fetcher import FetcherService
from app.models import Article
from app.schemas import ArticleFullResponse, ArticleIngest, ArticleResponse

logger = logging.getLogger(__name__)

router = APIRouter()


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
    Response matches the API contract shape exactly (id, source, title, body, published_at).
    """
    articles = (
        db.query(Article)
        .filter(Article.is_filtered == True)
        .order_by(Article.final_score.desc())
        .all()
    )
    logger.info(f"[/retrieve] Returning {len(articles)} filtered articles")
    return articles


@router.post("/fetch")
def trigger_fetch():
    """Trigger an immediate fetch and classification of all RSS sources. Blocks until complete."""
    FetcherService()._fetch_all(SessionLocal, classifier)
    return {"status": "ok"}


@router.get("/articles", response_model=List[ArticleFullResponse])
def articles_full(db: Session = Depends(get_db)):
    """
    Return all filtered articles with full classification fields for the UI.
    Same filtering and ordering as /retrieve but includes category, scores, ingested_at.
    """
    articles = (
        db.query(Article)
        .filter(Article.is_filtered == True)
        .order_by(Article.final_score.desc())
        .all()
    )
    logger.info(f"[/articles] Returning {len(articles)} articles with full detail")
    return articles
