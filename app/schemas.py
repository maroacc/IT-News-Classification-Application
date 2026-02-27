from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class ArticleIngest(BaseModel):
    """Shape expected from the /ingest endpoint — matches the API contract exactly."""
    id: str
    source: str
    title: str
    body: Optional[str] = None
    published_at: datetime


class ArticleResponse(BaseModel):
    """Shape returned by the /retrieve endpoint — matches the API contract exactly."""
    id: str
    source: str
    title: str
    body: Optional[str] = None
    published_at: datetime

    # Allows Pydantic to read data directly from SQLAlchemy model instances
    model_config = ConfigDict(from_attributes=True)
