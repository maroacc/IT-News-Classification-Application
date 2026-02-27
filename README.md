# IT-News-Classification-Application
Application to retrieve news from several IT sources, classify them according to categories and display them on a UI.

## Project Structure

```
IT-News-Classification-Application/
├── app/
│   ├── classifier.py     # Zero-shot classifier, scoring, DB persistence
│   ├── database.py       # SQLite engine, session factory, get_db() dependency
│   ├── fetcher.py        # RSS fetcher, background loop, source registry
│   ├── models.py         # SQLAlchemy ORM model (Article table)
│   ├── schemas.py        # Pydantic schemas for API input/output validation
│   └── routes/
│       └── articles.py   # /ingest, /retrieve, /articles route handlers
├── tests/
│   ├── test_classifier.py            # Classifier unit tests
│   ├── test_classifier_integration.py
│   ├── test_fetcher.py               # Fetcher unit tests
│   ├── test_fetcher_integration.py
│   ├── test_routes.py                # Route unit tests
│   └── test_routes_integration.py
├── main.py               # FastAPI app, lifespan (DB init + background fetcher)
├── requirements.txt      # Pinned dependencies
├── pytest.ini            # Pytest config (integration marker)
└── news.db               # SQLite database (created on first run)
```

---

## Getting Started

### Prerequisites
- Python 3.12
- pip

### Setup

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

### Running the app

```bash
uvicorn main:app --reload
```

On startup the app will:
1. Create `news.db` at the project root (if it doesn't exist)
2. Start a background fetcher that polls all RSS sources every 5 minutes
3. Classify and store each article automatically

The API will be available at `http://localhost:8000`.
Interactive API docs (Swagger UI) at `http://localhost:8000/docs`.

---

## API Reference

### `POST /ingest`
Ingest a batch of raw articles for classification and storage.

**Request body** — JSON array of article objects:
```json
[
  {
    "id": "unique-string",
    "source": "source-name",
    "title": "Article headline",
    "body": "Optional article body",
    "published_at": "2025-01-01T12:00:00Z"
  }
]
```

**Response** — HTTP 200:
```json
{ "status": "ok", "received": 1 }
```

---

### `GET /retrieve`
Returns all articles that passed the relevance filter, sorted by score descending. Response matches the API contract shape exactly.

**Response** — JSON array:
```json
[
  {
    "id": "unique-string",
    "source": "source-name",
    "title": "Article headline",
    "body": "Optional article body",
    "published_at": "2025-01-01T12:00:00Z"
  }
]
```

---

### `GET /articles`
Same filtering and ordering as `/retrieve` but returns the full internal schema including classification fields. Intended for the UI.

**Response** — JSON array with additional fields:
```json
[
  {
    "id": "unique-string",
    "source": "source-name",
    "title": "Article headline",
    "body": "Optional article body",
    "published_at": "2025-01-01T12:00:00Z",
    "importance_score": 0.87,
    "recency_score": 0.94,
    "final_score": 0.82,
    "category": "cybersecurity incident or data breach",
    "ingested_at": "2025-01-01T12:01:00Z"
  }
]
```

---

## Technical Decisions

### Framework — FastAPI + Streamlit
FastAPI handles the REST API (`/ingest`, `/retrieve`) due to its native async support, automatic request validation via Pydantic, and auto-generated docs. Streamlit is used for the UI — it allows building a functional web dashboard in pure Python with minimal overhead.

### Database — SQLite + SQLAlchemy ORM
SQLite keeps the project self-contained with no external dependencies (no database server to run). SQLAlchemy ORM is used to interact with the DB in Python without writing raw SQL, and makes it straightforward to swap to PostgreSQL later if needed.

**Single table design (PoC decision):** A single `articles` table stores all news items, already classified. Articles are classified and scored before being written to the database — meaning only enriched, processed records ever land in storage. This keeps the schema simple and queries fast for a proof of concept.

In a production scenario, a better approach would be a **two-table design**:
- A **landing table** receives raw articles immediately on ingestion, with no processing delay. This ensures data is never lost even if classification fails, and allows the ingest endpoint to respond fast.
- A **processed table** receives articles after classification, enriched with scores and category.
- The landing table can be cleaned up after a configurable retention period (e.g. delete records older than 7 days) to prevent unbounded growth.

This separation also makes it easier to reprocess articles if the classifier changes, since the raw data is always available.

### Classification — Zero-shot (`valhalla/distilbart-mnli-12-3`)
No labelled dataset was provided for this task, making supervised training impractical. Even if one were available, collecting a dataset large and diverse enough to outperform modern pre-trained models would require significant time and resources. Zero-shot models have advanced to the point where they generalise remarkably well across domains out of the box — making them the pragmatic and effective choice here.

Zero-shot classification allows us to define meaningful IT-manager-relevant categories (e.g. "system outage", "cybersecurity incident") without needing any labelled training data. The `valhalla/distilbart-mnli-12-3` model is a distilled version of BART-large-MNLI — a good balance between accuracy and speed for local/CPU use.

The classifier assigns a weighted importance score (0–1) based on predefined labels and their relevance to IT managers:

| Label                                    | Weight |
|------------------------------------------|--------|
| `cybersecurity incident or data breach`  | 1.0    |
| `system outage or service disruption`    | 1.0    |
| `critical software bug or vulnerability` | 0.9    |
| `software release or patch`              | 0.5    |
| `general technology news`                | 0.2    |

### Ranking — Importance × Recency
Each article is ranked by `final_score = importance_score × recency_score`, where:
- `importance_score` comes from the weighted zero-shot classifier output
- `recency_score = e^(-λ * hours_since_published)` — exponential decay with a ~24h half-life

Both scores are computed and stored **at ingestion time**, making the `/retrieve` endpoint fully deterministic regardless of when it is called.

### News Sources — RSS feeds
All sources (Reddit, Ars Technica, The Hacker News, Tom's Hardware) are fetched via RSS feeds — no API credentials required, and RSS is universally supported. The fetcher uses a **base class pattern** so new sources can be added by implementing a single `fetch()` method, with no changes to existing code.

| Source              | Feed                                                        |
|---------------------|-------------------------------------------------------------|
| Reddit r/sysadmin   | `https://www.reddit.com/r/sysadmin.rss`                    |
| Ars Technica        | `https://feeds.arstechnica.com/arstechnica/technology-lab` |
| The Hacker News     | `https://feeds.feedburner.com/TheHackersNews`               |
| Tom's Hardware      | `https://www.tomshardware.com/feeds/all`                    |

### Fetch Interval — Every 5 minutes
The background fetcher runs as a FastAPI startup task, polling all sources every 5 minutes. This provides near real-time updates while avoiding excessive load on the sources.

### RSS Feed Snapshot Model and Coverage
RSS feeds are static XML files served by the publisher. Each fetch returns a **snapshot** of whatever articles the site currently exposes — typically their 20–50 most recent items. There is no pagination and no way to request articles beyond that window. The number of articles per fetch is entirely controlled by the publisher:

| Source | Articles exposed per fetch |
|---|---|
| The Hacker News | ~50 |
| Tom's Hardware | ~25 |
| Reddit r/sysadmin | ~25 |
| Ars Technica | ~20 |

Each fetch cycle, new articles that have appeared since the last fetch will be present in the snapshot while old ones will have dropped off. As long as new articles appear slower than the feed rotates, no articles are missed. For IT news sites, a few articles per hour is typical — well within a 5-minute polling interval.

**What could be missed:** if a site published articles faster than the feed window rotates between fetches, the oldest items could drop off before we catch them. In practice this does not happen for IT news sources. A more robust solution would track the last seen article ID per source and alert if gaps are detected — but this is unnecessary overhead for the current use case.

### Filter Pass Rate by Source
After the first fetch cycle, the classifier accepted the following proportions per source:

| Source | Fetched | Passed filter | Pass rate |
|---|---|---|---|
| The Hacker News | 50 | 48 | 96% |
| Tom's Hardware | 26 | 17 | 65% |
| Reddit r/sysadmin | 25 | 23 | 92% |
| Ars Technica | 20 | 15 | 75% |
| **Total** | **121** | **103** | **85%** |

These rates reflect how well each source aligns with IT manager relevance. The Hacker News and Reddit r/sysadmin score very high because their content is almost entirely security incidents, outages, and critical bugs — exactly the categories with the highest label weights. Tom's Hardware covers general hardware reviews and product announcements alongside IT-relevant content, so more articles fall below the threshold. Ars Technica similarly mixes general technology coverage with IT-critical reporting.

This also serves as a sanity check on the classifier: a source like The Hacker News passing 96% makes intuitive sense, while a general tech publication passing everything would indicate the filter is too permissive.

### `/retrieve` scope — all filtered articles
Both articles fetched from RSS sources and articles injected via `/ingest` go through the same `classify_and_save()` pipeline and are stored in the same table. The `/retrieve` endpoint returns **all** articles marked `is_filtered = True`, regardless of their origin.

This is a deliberate design choice: the system is a unified newsfeed — the test harness articles and the live RSS articles are treated equally. The spec says `/retrieve` should return "only the events your system decided to keep", without restricting by source.

One implication: since the background fetcher continuously adds new articles, the result set of `/retrieve` can grow between calls. The **ordering is always deterministic** (scores are fixed at ingestion time), but **membership may grow** as new articles arrive. This is expected behaviour for a live newsfeed system.

---

## Database Layer

### `app/database.py`
Sets up the SQLite database using SQLAlchemy. Provides:
- `engine` — connects to `news.db` at the project root
- `SessionLocal` — session factory; each request gets its own session
- `get_db()` — FastAPI dependency that yields a session and closes it after use

### `app/models.py`
Defines the `Article` SQLAlchemy model (single table). Fields:

| Field | Type | Description |
|------------------|-----------------|------------------------------------------------------|
| `id` | String (PK) | ID from the source — not auto-generated |
| `source` | String | e.g. `"reddit"`, `"ars-technica"` |
| `title` | String | Article headline |
| `body` | Text (optional) | Article content |
| `published_at` | DateTime | UTC timestamp from the source |
| `importance_score` | Float | Weighted score from zero-shot classifier (0–1) |
| `recency_score` | Float | Exponential decay based on `published_at` (0–1) |
| `final_score` | Float | `importance * recency`, used for ranking in `/retrieve` |
| `is_filtered` | Boolean | `True` if article passed the classifier threshold |
| `category` | String | Winning label from the classifier |
| `ingested_at` | DateTime | When the article was received by the system |

### `app/schemas.py`
Pydantic schemas for request/response validation:
- `ArticleIngest` — validates incoming data from `POST /ingest`
- `ArticleResponse` — shapes outgoing data from `GET /retrieve`

Both match the API contract shape: `id`, `source`, `title`, `body`, `published_at`.

---

## Fetcher Layer

### `app/fetcher.py`
Fetches articles from all registered RSS sources, classifies them, and persists them to the database. Designed for modularity — adding a new source requires only a new subclass with two attributes.

**Key components:**

- `BaseSource` — abstract base class. Every source must implement `fetch() -> List[ArticleIngest]`.
- `RSSSource(BaseSource)` — shared RSS parsing logic (GUID extraction, HTML stripping, date parsing, error handling). All current sources inherit from this.
- Concrete sources — each defines only `source_name` and `feed_url`:
  - `RedditSysadminSource`
  - `ArsTechnicaSource`
  - `HackerNewsSource`
  - `TomsHardwareSource`
- `SOURCES` — a list acting as the source registry. Enable or disable a source by adding or removing it from this list.
- `FetcherService` — runs an async background loop every 5 minutes, calling `classify_and_save()` for each fetched article.

**Design decisions:**
- Errors in one source are logged and skipped — other sources are unaffected.
- Existing articles are overwritten on re-fetch (upsert by ID), so content updates are reflected.
- The fetcher runs synchronously (no `asyncio.to_thread`) for simplicity. In production, wrapping blocking I/O calls in a thread pool would prevent event loop blocking.

---

## Classifier Layer

### `app/classifier.py`
Scores each article for relevance to IT managers and persists the result to the database. Called by both the background fetcher and the `/ingest` route.

**Importance score:**
The zero-shot model returns confidence scores across all labels (summing to 1.0). Each confidence is multiplied by its label weight, and the results are summed to produce `importance_score`:

```
importance_score = sum(confidence[label] × weight[label])
```

Since confidences sum to 1.0, the score is naturally bounded:
- `0.2` — article is entirely general tech news
- `1.0` — article is entirely a cybersecurity incident or outage

Articles with `importance_score > 0.5` are marked `is_filtered = True` and appear in `/retrieve`.

**Recency score:**
Exponential decay with a 48-hour half-life:
```
recency_score = e^(-λ × hours_since_published)    where λ = ln(2) / 48 ≈ 0.0144
```
- At publication: `recency_score = 1.0`
- After 48h: `recency_score = 0.5`
- After 96h: `recency_score = 0.25`

**Final score:**
```
final_score = importance_score × recency_score
```
Used by `/retrieve` to sort articles by importance and freshness combined.

**Design decisions:**
- **Title only** is fed to the classifier. RSS bodies are often truncated or noisy; the title carries the most reliable signal.
- **Lazy model loading** — the model is loaded on the first classification call, keeping app startup fast.
- **Failure handling** — if classification fails, the article is still saved with null scores and `is_filtered = False`. No data is lost.
- **Shared singleton** — a single `classifier` instance is imported by both the fetcher and the `/ingest` route, so the model is only loaded once.
- **Category** is the label with the highest weighted score, used for display in the UI.

## Testing

The project separates **unit tests** (fast, no network, no model) from **integration tests** (real HTTP calls or real ML model).

### Running tests

| Command                                                | What it runs                                         |
|--------------------------------------------------------|------------------------------------------------------|
| `pytest tests/test_fetcher.py -v`                     | Fetcher unit tests — mocked feedparser               |
| `pytest tests/test_routes.py -v`                      | Route unit tests — mocked classifier, in-memory DB   |
| `pytest tests/test_classifier.py -v`                  | Classifier unit tests — mocked ML pipeline           |
| `pytest -m "not integration" -v`                      | All unit tests (fast, no network, no model)          |
| `pytest tests/test_fetcher_integration.py -v`         | Fetcher integration — hits real RSS feeds            |
| `pytest tests/test_routes_integration.py -v`          | Route integration — real classifier, in-memory DB    |
| `pytest tests/test_classifier_integration.py -v`      | Classifier integration — loads real ML model         |
| `pytest -m integration -v`                            | All integration tests                                |
| `pytest -v`                                           | Full test suite (unit + integration)                 |

### Unit tests

**`tests/test_fetcher.py`** — mocks `feedparser`, no HTTP calls. Covers:
- `strip_html`, `parse_date`, `RSSSource.fetch()`, `SOURCES` registry

**`tests/test_classifier.py`** — mocks the ML pipeline. Covers:
- `_compute_recency`, `_compute_importance`, `classify_and_save`

**`tests/test_routes.py`** — mocks the classifier, uses an in-memory SQLite database. Covers:
- `POST /ingest` — acknowledgment, batch count, validation errors, classifier called per article
- `GET /retrieve` — filtering, ordering, contract response shape (no classification fields leaked)
- `GET /articles` — full schema with classification fields, consistent ordering with `/retrieve`

#### Note on in-memory SQLite and StaticPool

Route tests use `sqlite:///:memory:` for speed and isolation — each test gets a fresh database that disappears when the test ends, with no files left on disk.

The catch: SQLite in-memory databases are **connection-scoped**. Each new connection gets its own private block of RAM, so a second connection sees a completely empty database even if the first one already created tables and inserted data. This matters because FastAPI runs route handlers in a thread pool, which can open a new database connection separate from the one the test fixture used.

The fix is SQLAlchemy's `StaticPool`: instead of a pool of multiple connections, it keeps a single connection and returns it every time one is requested. All parties — the fixture, the route handler, the test assertions — share the same connection, and therefore the same in-memory database.

### Integration tests

**`tests/test_fetcher_integration.py`** — real HTTP requests to each RSS feed. Verifies each source returns valid articles with all required fields.

**`tests/test_classifier_integration.py`** — loads the actual `valhalla/distilbart-mnli-12-3` model. Verifies relevant headlines pass the filter and irrelevant ones don't.

**`tests/test_routes_integration.py`** — real classifier + in-memory DB. Tests the full ingest → classify → retrieve pipeline end-to-end, including determinism and correct filtering.

> **Note:** Integration tests require an active internet connection (fetcher) or will trigger model loading (~300MB download on first run, cached after). Run `pytest -m "not integration"` to skip them.
