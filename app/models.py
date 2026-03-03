from sqlalchemy import Column, String, Float, Boolean, DateTime, Text, Integer
from datetime import datetime, timezone
from app.database import Base


class Article(Base):
    __tablename__ = "articles"

    # --- API contract fields ---
    # ID comes from the source (e.g. Reddit post ID, article URL hash) — not auto-generated
    id = Column(String, primary_key=True, index=True)
    source = Column(String, nullable=False)       # e.g. "reddit", "ars-technica"
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)            # optional per API contract
    published_at = Column(DateTime, nullable=False)  # UTC timestamp from source
    url = Column(String, nullable=True)           # link to the original article

    # --- Internal classification fields (populated at ingestion time) ---
    importance_score = Column(Float, nullable=True)  # weighted score from zero-shot classifier (0-1)
    is_filtered = Column(Boolean, default=False)     # True if article passed the classifier threshold
    category = Column(String, nullable=True)         # winning label from the classifier
    # recency_score and final_score are NOT stored — computed at retrieve time so they are always fresh

    # --- Metadata ---
    ingested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # when we received it


class RSSSourceModel(Base):
    __tablename__ = "sources"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    name     = Column(String, nullable=False)           # used as source slug on articles
    feed_url = Column(String, nullable=False, unique=True)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
