"""
Unit tests for the API routes — mocked classifier, in-memory SQLite database.
No model loading, no network calls. Fast.

Run with: pytest tests/test_routes.py -v
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Article
from app.routes.articles import router

# Minimal test app — no lifespan, no background fetcher
_app = FastAPI()
_app.include_router(router)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db):
    _app.dependency_overrides[get_db] = lambda: db
    yield TestClient(_app)
    _app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_payload(**kwargs) -> dict:
    """Returns a valid article payload dict, overridable via kwargs."""
    defaults = {
        "id": "test-id-1",
        "source": "test-source",
        "title": "Test Article",
        "body": None,
        "published_at": "2025-01-01T12:00:00Z",
    }
    defaults.update(kwargs)
    return defaults


def insert_article(db, **kwargs) -> Article:
    """Insert an Article directly into the DB, bypassing the classifier."""
    defaults = {
        "id": "article-1",
        "source": "test-source",
        "title": "Test Article",
        "body": None,
        "published_at": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "importance_score": 0.8,
        "recency_score": 0.9,
        "final_score": 0.72,
        "is_filtered": True,
        "category": "system outage or service disruption",
    }
    defaults.update(kwargs)
    article = Article(**defaults)
    db.add(article)
    db.commit()
    return article


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_returns_200_and_acknowledgment(self, client, db):
        with patch("app.routes.articles.classifier.classify_and_save") as mock_cls:
            mock_cls.return_value = MagicMock()
            response = client.post("/ingest", json=[make_payload()])

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["received"] == 1

    def test_classify_and_save_called_for_each_article(self, client, db):
        payload = [make_payload(id=f"id-{i}") for i in range(3)]
        with patch("app.routes.articles.classifier.classify_and_save") as mock_cls:
            mock_cls.return_value = MagicMock()
            client.post("/ingest", json=payload)

        assert mock_cls.call_count == 3

    def test_empty_batch_returns_zero_count(self, client, db):
        response = client.post("/ingest", json=[])
        assert response.status_code == 200
        assert response.json()["received"] == 0

    def test_missing_required_field_returns_422(self, client, db):
        # 'title' is required — omitting it should fail validation
        payload = [{"id": "x", "source": "y", "published_at": "2025-01-01T00:00:00Z"}]
        response = client.post("/ingest", json=payload)
        assert response.status_code == 422

    def test_batch_of_five_articles_accepted(self, client, db):
        payload = [make_payload(id=f"id-{i}", title=f"Article {i}") for i in range(5)]
        with patch("app.routes.articles.classifier.classify_and_save") as mock_cls:
            mock_cls.return_value = MagicMock()
            response = client.post("/ingest", json=payload)

        assert response.status_code == 200
        assert response.json()["received"] == 5

    def test_body_field_is_optional(self, client, db):
        payload = [make_payload(body=None)]
        with patch("app.routes.articles.classifier.classify_and_save") as mock_cls:
            mock_cls.return_value = MagicMock()
            response = client.post("/ingest", json=payload)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /retrieve
# ---------------------------------------------------------------------------

class TestRetrieve:
    def test_returns_only_filtered_articles(self, client, db):
        insert_article(db, id="keep", is_filtered=True,  final_score=0.9)
        insert_article(db, id="drop", is_filtered=False, final_score=0.3)

        ids = [a["id"] for a in client.get("/retrieve").json()]

        assert "keep" in ids
        assert "drop" not in ids

    def test_sorted_by_final_score_descending(self, client, db):
        insert_article(db, id="low",  is_filtered=True, final_score=0.3)
        insert_article(db, id="high", is_filtered=True, final_score=0.9)
        insert_article(db, id="mid",  is_filtered=True, final_score=0.6)

        ids = [a["id"] for a in client.get("/retrieve").json()]

        assert ids == ["high", "mid", "low"]

    def test_returns_empty_list_when_no_articles(self, client, db):
        response = client.get("/retrieve")
        assert response.status_code == 200
        assert response.json() == []

    def test_response_contains_all_contract_fields(self, client, db):
        insert_article(db, id="article-1")
        article = client.get("/retrieve").json()[0]

        assert "id" in article
        assert "source" in article
        assert "title" in article
        assert "body" in article
        assert "published_at" in article

    def test_response_does_not_contain_classification_fields(self, client, db):
        insert_article(db, id="article-1")
        article = client.get("/retrieve").json()[0]

        assert "importance_score" not in article
        assert "recency_score" not in article
        assert "final_score" not in article
        assert "category" not in article
        assert "is_filtered" not in article

    def test_response_shape_is_exactly_contract(self, client, db):
        insert_article(db, id="article-1")
        article = client.get("/retrieve").json()[0]

        assert set(article.keys()) == {"id", "source", "title", "body", "published_at"}


# ---------------------------------------------------------------------------
# GET /articles
# ---------------------------------------------------------------------------

class TestArticlesFull:
    def test_returns_classification_fields(self, client, db):
        insert_article(db, id="article-1", category="system outage or service disruption",
                       importance_score=0.8, recency_score=0.9, final_score=0.72)
        article = client.get("/articles").json()[0]

        assert article["category"] == "system outage or service disruption"
        assert article["importance_score"] == pytest.approx(0.8)
        assert article["recency_score"] == pytest.approx(0.9)
        assert article["final_score"] == pytest.approx(0.72)

    def test_excludes_non_filtered_articles(self, client, db):
        insert_article(db, id="filtered",     is_filtered=True)
        insert_article(db, id="not-filtered", is_filtered=False)

        ids = [a["id"] for a in client.get("/articles").json()]

        assert "filtered" in ids
        assert "not-filtered" not in ids

    def test_same_ordering_as_retrieve(self, client, db):
        insert_article(db, id="low",  is_filtered=True, final_score=0.3)
        insert_article(db, id="high", is_filtered=True, final_score=0.9)

        retrieve_ids = [a["id"] for a in client.get("/retrieve").json()]
        articles_ids = [a["id"] for a in client.get("/articles").json()]

        assert retrieve_ids == articles_ids

    def test_also_contains_base_contract_fields(self, client, db):
        insert_article(db, id="article-1")
        article = client.get("/articles").json()[0]

        assert "id" in article
        assert "source" in article
        assert "title" in article
        assert "body" in article
        assert "published_at" in article

    def test_ingested_at_is_present(self, client, db):
        insert_article(db, id="article-1")
        article = client.get("/articles").json()[0]

        assert "ingested_at" in article