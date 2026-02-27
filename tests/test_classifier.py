import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.classifier import (
    IMPORTANCE_THRESHOLD,
    LABEL_WEIGHTS,
    RECENCY_LAMBDA,
    ClassifierService,
)
from app.schemas import ArticleIngest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_article(**kwargs) -> ArticleIngest:
    """Creates an ArticleIngest with sensible defaults, overridable via kwargs."""
    defaults = {
        "id": "test-id-1",
        "source": "test-source",
        "title": "Test Article",
        "body": None,
        "published_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    return ArticleIngest(**defaults)


def mock_pipeline(labels, scores):
    """Returns a mock callable that mimics the zero-shot pipeline output."""
    pipe = MagicMock(return_value={"labels": labels, "scores": scores})
    return pipe


LABELS = list(LABEL_WEIGHTS.keys())


# ---------------------------------------------------------------------------
# _compute_recency
# ---------------------------------------------------------------------------

class TestComputeRecency:
    def setup_method(self):
        self.service = ClassifierService()

    def test_freshly_published_scores_near_one(self):
        score = self.service._compute_recency(datetime.now(timezone.utc))
        assert 0.99 <= score <= 1.0

    def test_48h_old_scores_near_half(self):
        # 48h is the half-life — score should be exactly 0.5
        published = datetime.now(timezone.utc) - timedelta(hours=48)
        score = self.service._compute_recency(published)
        assert abs(score - 0.5) < 0.01

    def test_96h_old_scores_near_quarter(self):
        # Two half-lives → 0.25
        published = datetime.now(timezone.utc) - timedelta(hours=96)
        score = self.service._compute_recency(published)
        assert abs(score - 0.25) < 0.01

    def test_future_dated_article_clamped_to_one(self):
        # Articles with a future published_at should not score above 1.0
        future = datetime.now(timezone.utc) + timedelta(hours=10)
        score = self.service._compute_recency(future)
        assert score == 1.0

    def test_naive_datetime_handled_without_error(self):
        # published_at may arrive without tzinfo — must not raise
        naive = datetime.now().replace(tzinfo=None)  # intentionally naive for this test
        score = self.service._compute_recency(naive)
        assert 0.0 < score <= 1.0

    def test_score_decreases_over_time(self):
        recent = datetime.now(timezone.utc) - timedelta(hours=10)
        older = datetime.now(timezone.utc) - timedelta(hours=50)
        assert self.service._compute_recency(recent) > self.service._compute_recency(older)

    def test_decay_formula_is_correct(self):
        hours = 24
        published = datetime.now(timezone.utc) - timedelta(hours=hours)
        expected = math.exp(-RECENCY_LAMBDA * hours)
        score = self.service._compute_recency(published)
        assert abs(score - expected) < 0.01


# ---------------------------------------------------------------------------
# _compute_importance
# ---------------------------------------------------------------------------

class TestComputeImportance:
    def setup_method(self):
        self.service = ClassifierService()

    def test_high_security_confidence_gives_high_score(self):
        # 90% confidence on cybersecurity (weight=1.0) → should pass filter
        scores = [0.9, 0.05, 0.02, 0.02, 0.01]
        with patch.object(self.service, "_get_pipeline", return_value=mock_pipeline(LABELS, scores)):
            score, category = self.service._compute_importance("test")

        assert score > IMPORTANCE_THRESHOLD
        assert category == "cybersecurity incident or data breach"

    def test_high_general_news_confidence_gives_low_score(self):
        # 96% confidence on general tech news (weight=0.2) → should fail filter
        scores = [0.01, 0.01, 0.01, 0.01, 0.96]
        with patch.object(self.service, "_get_pipeline", return_value=mock_pipeline(LABELS, scores)):
            score, category = self.service._compute_importance("test")

        assert score < IMPORTANCE_THRESHOLD
        assert category == "general technology news"

    def test_weighted_score_calculation_is_correct(self):
        # Verify the weighted sum formula manually
        scores = [0.5, 0.2, 0.1, 0.1, 0.1]
        expected = (
            0.5 * 1.0 +  # cybersecurity incident
            0.2 * 1.0 +  # system outage
            0.1 * 0.9 +  # critical software bug
            0.1 * 0.5 +  # software release
            0.1 * 0.2    # general technology news
        )
        with patch.object(self.service, "_get_pipeline", return_value=mock_pipeline(LABELS, scores)):
            score, _ = self.service._compute_importance("test")

        assert abs(score - expected) < 1e-6

    def test_category_is_label_with_highest_weighted_score(self):
        # Outage label (index 1) gets highest confidence → should win
        scores = [0.1, 0.7, 0.1, 0.05, 0.05]
        with patch.object(self.service, "_get_pipeline", return_value=mock_pipeline(LABELS, scores)):
            _, category = self.service._compute_importance("test")

        assert category == "system outage or service disruption"

    def test_score_is_within_expected_range(self):
        # Score must always be between min_weight (0.2) and max_weight (1.0)
        scores = [0.2, 0.2, 0.2, 0.2, 0.2]
        with patch.object(self.service, "_get_pipeline", return_value=mock_pipeline(LABELS, scores)):
            score, _ = self.service._compute_importance("test")

        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# classify_and_save
# ---------------------------------------------------------------------------

class TestClassifyAndSave:
    def setup_method(self):
        self.service = ClassifierService()

    def test_saves_article_with_correct_scores(self):
        article = make_article()
        db = MagicMock()

        with patch.object(self.service, "_compute_importance", return_value=(0.8, "system outage or service disruption")):
            with patch.object(self.service, "_compute_recency", return_value=0.9):
                result = self.service.classify_and_save(article, db)

        assert result.importance_score == 0.8
        assert result.recency_score == 0.9
        assert abs(result.final_score - 0.72) < 1e-6
        assert result.category == "system outage or service disruption"
        assert result.is_filtered is True  # 0.8 > 0.5

    def test_is_filtered_false_when_below_threshold(self):
        article = make_article()
        db = MagicMock()

        with patch.object(self.service, "_compute_importance", return_value=(0.3, "general technology news")):
            with patch.object(self.service, "_compute_recency", return_value=0.9):
                result = self.service.classify_and_save(article, db)

        assert result.is_filtered is False

    def test_db_merge_and_commit_are_called(self):
        article = make_article()
        db = MagicMock()

        with patch.object(self.service, "_compute_importance", return_value=(0.8, "system outage or service disruption")):
            with patch.object(self.service, "_compute_recency", return_value=0.9):
                self.service.classify_and_save(article, db)

        db.merge.assert_called_once()
        db.commit.assert_called_once()

    def test_saves_with_null_scores_on_classification_failure(self):
        # Even if the model crashes, the article must still be persisted
        article = make_article()
        db = MagicMock()

        with patch.object(self.service, "_compute_importance", side_effect=Exception("model error")):
            result = self.service.classify_and_save(article, db)

        assert result.importance_score is None
        assert result.recency_score is None
        assert result.final_score is None
        assert result.is_filtered is False
        db.merge.assert_called_once()  # still saved despite failure
        db.commit.assert_called_once()

    def test_article_fields_are_persisted_correctly(self):
        published = datetime.now(timezone.utc)
        article = make_article(id="abc-123", source="ars-technica", title="Big Outage", published_at=published)
        db = MagicMock()

        with patch.object(self.service, "_compute_importance", return_value=(0.9, "system outage or service disruption")):
            with patch.object(self.service, "_compute_recency", return_value=1.0):
                result = self.service.classify_and_save(article, db)

        assert result.id == "abc-123"
        assert result.source == "ars-technica"
        assert result.title == "Big Outage"
        assert result.published_at == published