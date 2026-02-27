"""
Integration tests for the API routes — real classifier, in-memory SQLite database.
Tests the full ingest → classify → retrieve pipeline end-to-end.

The first run will load the model (~300MB). Subsequent runs use the cache.

Run with: pytest tests/test_routes_integration.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.routes.articles import router

pytestmark = pytest.mark.integration

# Minimal test app — no lifespan, no background fetcher
_app = FastAPI()
_app.include_router(router)

# ---------------------------------------------------------------------------
# Test data — mix of clearly relevant and clearly irrelevant headlines
# ---------------------------------------------------------------------------

RELEVANT_BATCH = [
    {
        "id": "r1", "source": "test",
        "title": "Critical ransomware attack shuts down hospital network",
        "body": None, "published_at": "2025-01-01T12:00:00Z",
    },
    {
        "id": "r2", "source": "test",
        "title": "Major AWS outage takes down us-east-1 for 4 hours",
        "body": None, "published_at": "2025-01-01T11:00:00Z",
    },
    {
        "id": "r3", "source": "test",
        "title": "Zero-day vulnerability found in Windows kernel — patch now",
        "body": None, "published_at": "2025-01-01T10:00:00Z",
    },
]

IRRELEVANT_BATCH = [
    {
        "id": "i1", "source": "test",
        "title": "Apple announces new MacBook Pro with M4 chip",
        "body": None, "published_at": "2025-01-01T12:00:00Z",
    },
    {
        "id": "i2", "source": "test",
        "title": "Google celebrates 25th anniversary with a new logo",
        "body": None, "published_at": "2025-01-01T11:00:00Z",
    },
]


# ---------------------------------------------------------------------------
# Module-scoped fixture — ingests all test data once, model loaded once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def populated_client():
    """
    Creates a fresh in-memory DB, ingests all test batches via the API,
    and yields a ready-to-query TestClient.
    Model is loaded once for the entire module.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    _app.dependency_overrides[get_db] = lambda: db
    client = TestClient(_app)

    response = client.post("/ingest", json=RELEVANT_BATCH + IRRELEVANT_BATCH)
    assert response.status_code == 200, "Ingest during setup failed"

    yield client

    db.close()
    _app.dependency_overrides.clear()
    engine.dispose()


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

class TestIngestIntegration:
    def test_ingest_returns_correct_count(self, populated_client):
        # Re-ingest is an upsert — won't create duplicates, just verifies the endpoint
        response = populated_client.post("/ingest", json=RELEVANT_BATCH)
        assert response.status_code == 200
        assert response.json()["received"] == len(RELEVANT_BATCH)


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------

class TestRetrieveIntegration:
    def test_relevant_articles_are_returned(self, populated_client):
        ids = {a["id"] for a in populated_client.get("/retrieve").json()}
        for article in RELEVANT_BATCH:
            assert article["id"] in ids, \
                f"Expected relevant article '{article['id']}' to be in /retrieve"

    def test_irrelevant_articles_are_excluded(self, populated_client):
        ids = {a["id"] for a in populated_client.get("/retrieve").json()}
        for article in IRRELEVANT_BATCH:
            assert article["id"] not in ids, \
                f"Expected irrelevant article '{article['id']}' to be excluded from /retrieve"

    def test_retrieve_is_deterministic(self, populated_client):
        first  = populated_client.get("/retrieve").json()
        second = populated_client.get("/retrieve").json()
        assert first == second, "/retrieve must return the same result on repeated calls"

    def test_retrieve_sorted_by_score_descending(self, populated_client):
        # Use /articles (which exposes scores) to verify the ordering from /retrieve
        articles = populated_client.get("/articles").json()
        scores = [a["final_score"] for a in articles]
        assert scores == sorted(scores, reverse=True), \
            "Articles must be sorted by final_score descending"

    def test_retrieve_response_shape_matches_contract(self, populated_client):
        articles = populated_client.get("/retrieve").json()
        assert len(articles) > 0
        for article in articles:
            assert set(article.keys()) == {"id", "source", "title", "body", "published_at"}, \
                f"Unexpected fields in /retrieve response: {set(article.keys())}"


# ---------------------------------------------------------------------------
# Articles (full schema)
# ---------------------------------------------------------------------------

class TestArticlesFullIntegration:
    def test_scores_are_populated(self, populated_client):
        articles = populated_client.get("/articles").json()
        assert len(articles) > 0
        for article in articles:
            assert article["importance_score"] is not None
            assert article["recency_score"] is not None
            assert article["final_score"] is not None

    def test_category_is_populated(self, populated_client):
        articles = populated_client.get("/articles").json()
        for article in articles:
            assert article["category"] is not None
            assert len(article["category"]) > 0

    def test_same_articles_as_retrieve(self, populated_client):
        retrieve_ids = {a["id"] for a in populated_client.get("/retrieve").json()}
        articles_ids = {a["id"] for a in populated_client.get("/articles").json()}
        assert retrieve_ids == articles_ids, \
            "/articles and /retrieve must return the same set of articles"
