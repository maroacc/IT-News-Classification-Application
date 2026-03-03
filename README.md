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
├── streamlit_app.py      # Streamlit dashboard (calls GET /articles)
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

The application has two components that run in separate terminals.

**Terminal 1 — API server**

```bash
uvicorn main:app --reload
```

On startup the app will:
1. Create `news.db` at the project root (if it doesn't exist)
2. Start a background fetcher that polls all RSS sources every 5 minutes
3. Classify and store each article automatically

The API will be available at `http://localhost:8000`.
Interactive API docs (Swagger UI) at `http://localhost:8000/docs`.

**Terminal 2 — Streamlit dashboard**

```bash
streamlit run streamlit_app.py
```

The dashboard will open automatically in your browser at `http://localhost:8501`.

It calls `GET /articles` to display classified articles in a card layout. The API server must be running first.

**Sidebar controls:**
- **Refresh now** — triggers an immediate fetch and classification cycle
- **Auto-refresh** — toggle to automatically reload the feed every 5 minutes
- **Category filter** — multiselect to show/hide specific categories
- **Source filter** — multiselect to show/hide specific RSS sources
- **Sort by** — choose between *Final score* (importance × recency, default), *Importance* (classifier score only), or *Most recent* (publication date)

**Article cards** show the category emoji, source, time since publication, title (as a clickable link to the original article when a URL is available), a 200-character body snippet, and three scores (importance, recency, final) displayed compactly on the right side of the card.

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

**Streamlit is suitable for this PoC but not for production with multiple users.** Key limitations:

- **Full page re-render on every interaction** — Streamlit has no concept of partial updates. Any filter change, button click, or auto-refresh reruns the entire Python script from top to bottom and redraws the whole page. For a single user this is acceptable; for many concurrent users it becomes slow and resource-heavy.
- **No true multi-user session isolation** — Streamlit's session state is per-browser-tab, but the server runs a single Python process. Under concurrent load, blocking operations (like the auto-refresh sleep) affect all sessions.
- **Limited UI customisation** — layout, styling, and interactivity are constrained by what Streamlit exposes. Building a production-grade newsfeed UI with real-time updates, pagination, or user preferences would require a proper frontend framework (React, Vue, etc.).
- **Not designed for horizontal scaling** — Streamlit apps are stateful and tied to a single process, making them hard to scale behind a load balancer.

For the intended use case — **a single IT manager checking the feed** — these limitations are irrelevant. Streamlit delivers a functional, readable dashboard with minimal code, which is exactly what a PoC requires.

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

| Label                                       | Weight |
|---------------------------------------------|--------|
| `cybersecurity incident or data breach`     | 1.0    |
| `system outage or service disruption`       | 1.0    |
| `critical software bug or vulnerability`    | 0.9    |
| `software release or patch`                 | 0.5    |
| `general technology news`                   | 0.2    |
| `IT community discussion or advice request` | 0.15   |

The sixth label (`IT community discussion or advice request`) was added after analysis revealed that Reddit r/sysadmin posts — which are forum discussions, not news articles — were being forced into high-weight categories like "system outage" and passing the filter incorrectly. A dedicated low-weight label (0.15, below the 0.5 threshold) gives the model a correct bucket for community content, causing it to be filtered out automatically.

### Model loading — eager, background thread

The ML model (~300MB) is loaded **eagerly at startup** rather than lazily on the first classification request. This avoids an unexpected multi-second stall on the first `/ingest` or `/fetch` call after the server starts.

Loading happens in a **daemon background thread** (`threading.Thread(target=classifier.load, daemon=True).start()`) so the server becomes reachable within seconds. The model finishes loading in parallel — typically ~60s on first run (download + load), near-instant on subsequent runs (cached locally by HuggingFace).

A public `load()` method was added to `ClassifierService` (calling the existing internal `_get_pipeline()`) along with an `is_ready` property, so the startup logic can interact with a clean public API without reaching into private internals.

**`GET /health`** exposes readiness to callers. Returns `{"status": "loading"}` while the model is initialising, and `{"status": "ready"}` once all endpoints are fully operational.

The Streamlit dashboard polls `/health` every 2 seconds on startup and shows a *"ML model is loading…"* spinner instead of a confusing connection error. Once `"ready"` is returned, the dashboard fetches and renders articles normally.

### Ranking — Importance × Recency
Each article is ranked by `final_score = importance_score × recency_score`, where:
- `importance_score` comes from the weighted zero-shot classifier output — computed **at fetch time** and stored in the database
- `recency_score = e^(-λ * hours_since_published)` — computed **at retrieve time**, so it always reflects the article's true age at the moment of the request

`importance_score` is the only score persisted. `recency_score` and `final_score` are computed fresh on every call to `/retrieve` and `/articles` and injected into the response. This means the ranking automatically degrades older articles over time without any reprocessing — an article fetched yesterday will rank lower today than it did yesterday.

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
| `url` | String (optional) | Link to the original article, populated from the RSS `link` field. Stored separately from `id` because some sources (e.g. Tom's Hardware) use non-URL GUIDs as their RSS entry ID. |
| `importance_score` | Float | Weighted score from zero-shot classifier (0–1) — stored at fetch time |
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
- `RSSSource(BaseSource)` — shared RSS parsing logic (GUID extraction, HTML stripping, date parsing, error handling). All current sources inherit from this. The RSS `link` field is stored separately as `url` — distinct from `id` — because some sources use non-URL GUIDs as their RSS entry identifier (e.g. Tom's Hardware uses random strings; Reddit uses `t3_<post_id>` formatted URLs that don't resolve to the article).
- Concrete sources — each defines only `source_name` and `feed_url`:
  - `RedditSysadminSource`
  - `ArsTechnicaSource`
  - `HackerNewsSource`
  - `TomsHardwareSource`
- `SOURCES` — a list acting as the source registry. Enable or disable a source by adding or removing it from this list.
- `FetcherService` — runs an async background loop every 5 minutes, calling `classify_and_save()` for each fetched article.

**Design decisions:**
- Errors in one source are logged and skipped — other sources are unaffected.
- **Skip-if-unchanged** — before running ML inference, `classify_and_save()` checks whether an article with the same ID already exists in the DB with identical `title` and `body`. If so, the existing record is returned immediately and classification is skipped entirely. If the content has changed, the article is re-classified and updated. This avoids redundant ML inference on every fetch cycle for articles that haven't changed.
- `_fetch_all` runs inside `loop.run_in_executor(None, ...)` so the blocking RSS + ML work happens in a thread pool and never stalls FastAPI's event loop. Incoming requests are handled normally while a fetch cycle is in progress.
- A 5-second delay is inserted before the first fetch cycle at startup, giving the server time to finish initialising and become reachable before the first (potentially slow) classification run begins.

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

**Recency score** *(computed at retrieve time, not stored):*
Exponential decay with a 48-hour half-life:
```
recency_score = e^(-λ × hours_since_published)    where λ = ln(2) / 48 ≈ 0.0144
```
- At publication: `recency_score = 1.0`
- After 48h: `recency_score = 0.5`
- After 96h: `recency_score = 0.25`

**Final score** *(computed at retrieve time, not stored):*
```
final_score = importance_score × recency_score
```
Computed fresh on every `/retrieve` and `/articles` request. Sorting happens in Python after score computation, since the value is not persisted in the database.

**Design decisions:**
- **Title + body snippet** is fed to the classifier. The article title alone is often insufficient to distinguish real news from community forum posts — a Reddit post titled *"HELP PLEASE! Had my first real email compromise incident this week"* is indistinguishable from a news headline without the body context. The first 300 characters of the body are appended to the title before classification, giving the model enough context to detect the conversational tone of forum posts. 300 characters was chosen as a balance between signal and inference speed.
- **Lazy model loading** — the model is loaded on the first classification call, keeping app startup fast.
- **Skip-if-unchanged** — `classify_and_save()` checks for an existing DB record with the same ID before classifying. If `title` and `body` are identical, classification is skipped and the existing record is returned. If the content has changed, the article is re-classified and the record updated. `title + body` was chosen as the change signal since they are the only fields that affect the classification result. The zero-shot model is deterministic at inference time (transformer models run in eval mode with dropout disabled, so identical inputs always produce identical outputs), so strictly speaking re-classifying unchanged content would yield the same scores. The skip-if-unchanged check is a precautionary measure that also avoids unnecessary CPU overhead on each fetch cycle.
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
- `_compute_recency`, `_compute_importance`, `classify_and_save`, skip-if-unchanged
- `classify_and_save` tests no longer assert on `recency_score` or `final_score` — those are not stored, only `importance_score`, `category`, and `is_filtered` are verified
- Score arrays in `_compute_importance` tests have 6 elements — one per label including "IT community discussion or advice request". Previously they had 5, causing `zip` to silently drop the new label from the weighted sum
- `TestSkipIfUnchanged` covers all four branches: unchanged article (skips inference), title changed (re-classifies), body changed (re-classifies), no existing record (classifies normally)

**`tests/test_routes.py`** — mocks the classifier, uses an in-memory SQLite database. Covers:
- `POST /ingest` — acknowledgment, batch count, validation errors, classifier called per article
- `GET /retrieve` — filtering, ordering, contract response shape (no classification fields leaked)
- `GET /articles` — full schema with classification fields, consistent ordering with `/retrieve`
- Sort order tests use `importance_score` and `published_at=now` (recency ≈ 1.0) to control ranking, since `final_score` is no longer stored and ordering happens in Python at request time
- Classification field tests assert that `recency_score` and `final_score` are present and within `(0, 1]` rather than exact values, since they are computed dynamically at request time

#### Note on in-memory SQLite and StaticPool

Route tests use `sqlite:///:memory:` for speed and isolation — each test gets a fresh database that disappears when the test ends, with no files left on disk.

The catch: SQLite in-memory databases are **connection-scoped**. Each new connection gets its own private block of RAM, so a second connection sees a completely empty database even if the first one already created tables and inserted data. This matters because FastAPI runs route handlers in a thread pool, which can open a new database connection separate from the one the test fixture used.

The fix is SQLAlchemy's `StaticPool`: instead of a pool of multiple connections, it keeps a single connection and returns it every time one is requested. All parties — the fixture, the route handler, the test assertions — share the same connection, and therefore the same in-memory database.

### Integration tests

**`tests/test_fetcher_integration.py`** — real HTTP requests to each RSS feed. Verifies each source returns valid articles with all required fields.

**`tests/test_classifier_integration.py`** — loads the actual `valhalla/distilbart-mnli-12-3` model. Verifies relevant headlines pass the filter and irrelevant ones don't.

**`tests/test_routes_integration.py`** — real classifier + in-memory DB. Tests the full ingest → classify → retrieve pipeline end-to-end, including determinism and correct filtering.

> **Note:** Integration tests require an active internet connection (fetcher) or will trigger model loading (~300MB download on first run, cached after). Run `pytest -m "not integration"` to skip them.

---

## Potential Improvements

### Classifier
- **Weighted final score formula** — the current formula `final_score = importance_score × recency_score` gives recency equal multiplicative power. A weighted sum like `0.7 × importance + 0.3 × recency` would let importance dominate ranking more explicitly, keeping older but highly relevant articles more visible.
- **Longer body context** — the classifier currently uses the first 300 characters of the body. Using more (e.g. 512 tokens worth) would give the model more signal, at the cost of slower inference.
- **Re-classification without DB wipe** — changing the classifier (new labels, new weights) currently requires deleting the database and re-fetching everything. A `/reclassify` endpoint that reruns the classifier on all stored articles without re-fetching would make iteration faster.
- **Confidence threshold per label** — instead of a single global importance threshold, each label could have its own minimum confidence to pass, giving finer control over which types of events are surfaced.

### Data sources
- **Reddit r/sysadmin** — even with the new "IT community discussion" category, some Reddit posts still slip through because their titles resemble news headlines. This source could be removed entirely, or a higher per-source confidence threshold could be applied to reduce noise.
- **More sources** — adding sources like BleepingComputer, Dark Reading, or vendor security bulletins would improve coverage of cybersecurity and software vulnerability news specifically.
- **Source management from the UI** — currently, adding or removing RSS sources requires editing `app/fetcher.py` and restarting the server. A source management page in the UI would let the IT manager add any RSS feed URL, name it, and remove sources they find noisy — all without touching code.
- **Full article scraping** — RSS bodies are often truncated. Scraping the full article text would give the classifier much richer context for difficult cases.

### Database
- **Two-table design** — separate raw ingestion from classified storage (see the existing note in the Database section). This would allow re-classification without data loss and make the ingest endpoint faster.
- **PostgreSQL** — replacing SQLite with PostgreSQL would support concurrent writes, connection pooling, and horizontal scaling. SQLAlchemy's ORM means this is a one-line change to the connection string.
- **Retention policy** — old articles accumulate indefinitely. A scheduled cleanup job deleting articles older than N days would keep the database from growing unboundedly.

### API & infrastructure
- **Docker** — containerising the API and Streamlit app would make deployment reproducible and remove the need to manage the virtual environment manually. A `docker-compose.yml` could start both services with a single command and enforce startup order.
- **Authentication** — the API currently has no authentication. Any process that can reach port 8000 can ingest or retrieve articles. Adding an API key header would be the minimal production requirement.
- **Alerting** — for a real IT manager use case, high-priority articles (e.g. `importance_score > 0.9`) could trigger a notification (email, Slack, PagerDuty) rather than waiting for the user to check the dashboard.
- **Pagination** — the `/retrieve` and `/articles` endpoints currently return all matching articles. As the database grows, adding `limit` and `offset` query parameters would keep response sizes manageable.

### UI
- **Replace Streamlit with a proper frontend** — as noted in the framework section, Streamlit rerenders the entire page on every interaction and does not scale to multiple users. A React or Vue frontend calling the FastAPI directly would provide real-time updates, better performance, and full UI flexibility.
- **Read/unread state** — the dashboard currently shows all articles on every load. Tracking which articles the user has already seen and only surfacing new ones would make the feed much more actionable.
