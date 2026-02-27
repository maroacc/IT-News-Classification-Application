from sqlalchemy import Column, String, Float, Boolean, DateTime, Text
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

    # --- Internal classification fields (populated at ingestion time) ---
    importance_score = Column(Float, nullable=True)  # weighted score from zero-shot classifier (0-1)
    recency_score = Column(Float, nullable=True)     # exponential decay based on published_at (0-1)
    final_score = Column(Float, nullable=True)       # importance * recency, used for ranking
    is_filtered = Column(Boolean, default=False)     # True if article passed the classifier threshold
    category = Column(String, nullable=True)         # winning label from the classifier

    # --- Metadata ---
    ingested_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))  # when we received it
