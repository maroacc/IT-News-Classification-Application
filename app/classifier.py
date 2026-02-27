import logging
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Article
from app.schemas import ArticleIngest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Label weights — reflect relevance to IT managers (higher = more important)
# ---------------------------------------------------------------------------

LABEL_WEIGHTS: dict[str, float] = {
    "cybersecurity incident or data breach":  1.0,
    "system outage or service disruption":    1.0,
    "critical software bug or vulnerability": 0.9,
    "software release or patch":              0.5,
    "general technology news":                0.2,
}

# importance_score = sum(confidence * weight) across all labels
# Since classifier confidences sum to 1.0, the score is naturally in [0.2, 1.0]:
#   - 0.2 → article is purely general tech news (lowest weight)
#   - 1.0 → article is purely a cybersecurity/outage event (highest weight)
IMPORTANCE_THRESHOLD = 0.5  # minimum importance_score to mark is_filtered = True

# ---------------------------------------------------------------------------
# Recency decay — exponential decay with 48h half-life
# λ = ln(2) / half_life_hours
# ---------------------------------------------------------------------------

RECENCY_HALF_LIFE_HOURS = 48
RECENCY_LAMBDA = math.log(2) / RECENCY_HALF_LIFE_HOURS  # ≈ 0.0144


class ClassifierService:
    """
    Classifies articles using a zero-shot NLI model.
    The model is loaded lazily on the first classification call.
    """

    def __init__(self):
        self._pipeline = None  # loaded on first use to keep startup fast

    def _get_pipeline(self):
        """Load and cache the zero-shot classification pipeline on first call."""
        if self._pipeline is None:
            from transformers import pipeline  # imported here to defer heavy load
            logger.info("Loading zero-shot classification model (first use — this may take a moment)...")
            self._pipeline = pipeline(
                "zero-shot-classification",
                model="valhalla/distilbart-mnli-12-3",
            )
            logger.info("Model loaded successfully")
        return self._pipeline

    def _compute_importance(self, title: str) -> tuple[float, str]:
        """
        Run zero-shot classification on the article title.

        Returns:
            importance_score: weighted sum of (confidence × label_weight), range [0.2, 1.0]
            category: the label with the highest weighted score
        """
        pipe = self._get_pipeline()
        result = pipe(title, candidate_labels=list(LABEL_WEIGHTS.keys()))

        # Map each label to its weighted score (confidence × weight)
        weighted_scores = {
            label: score * LABEL_WEIGHTS[label]
            for label, score in zip(result["labels"], result["scores"])
        }

        importance_score = sum(weighted_scores.values())
        category = max(weighted_scores, key=weighted_scores.get)

        return importance_score, category

    def _compute_recency(self, published_at: datetime) -> float:
        """
        Compute a recency score using exponential decay.
        Score is 1.0 at publication time, 0.5 after 48h, approaches 0 over time.

        Args:
            published_at: UTC datetime of publication

        Returns:
            recency_score in range (0, 1]
        """
        # Ensure the datetime is timezone-aware before subtracting
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        hours_elapsed = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
        hours_elapsed = max(0.0, hours_elapsed)  # guard against future-dated articles

        return math.exp(-RECENCY_LAMBDA * hours_elapsed)

    def classify_and_save(self, article: ArticleIngest, db: Session) -> Article:
        """
        Classify an article, compute its scores, and upsert it into the database.

        On classification failure, the article is still saved with null scores
        and is_filtered = False so no data is lost.

        Args:
            article: the incoming article to classify
            db: active SQLAlchemy session

        Returns:
            the saved Article ORM object
        """
        importance_score = None
        recency_score = None
        final_score = None
        category = None
        is_filtered = False

        try:
            importance_score, category = self._compute_importance(article.title)
            recency_score = self._compute_recency(article.published_at)
            final_score = importance_score * recency_score
            is_filtered = importance_score > IMPORTANCE_THRESHOLD

            imp_str = f"{importance_score:.3f}"
            final_str = f"{final_score:.3f}"
            status = "PASS" if is_filtered else "FAIL"
            logger.info(
                f"[{article.source}] [{status}] '{article.title[:60]}' "
                f"(importance={imp_str}, recency={recency_score:.3f}, final={final_str}, category='{category}')"
            )

        except Exception as e:
            logger.error(f"Classification failed for article '{article.id}': {e}")

        db_article = Article(
            id=article.id,
            source=article.source,
            title=article.title,
            body=article.body,
            published_at=article.published_at,
            importance_score=importance_score,
            recency_score=recency_score,
            final_score=final_score,
            is_filtered=is_filtered,
            category=category,
        )

        # merge() performs an upsert — inserts if new, updates if ID already exists
        db.merge(db_article)
        db.commit()

        return db_article


# Shared singleton — imported by the fetcher and the /ingest route
classifier = ClassifierService()