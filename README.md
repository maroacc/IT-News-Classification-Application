# IT-News-Classification-Application
Application to retrieve news from several IT sources, classify them according to categories and display them on a UI.

## Project Structure

```
IT-News-Classification-Application/
├── app/
│   ├── classifier.py     # Zero-shot classifier, scoring, DB persistence
│   ├── database.py       # PostgreSQL engine, DATABASE_URL config, get_db() dependency
│   ├── fetcher.py        # RSS fetcher, background loop, DB-backed source registry
│   ├── models.py         # SQLAlchemy ORM models (Article, RSSSourceModel tables)
│   ├── schemas.py        # Pydantic schemas for API input/output validation
│   └── routes/
│       └── articles.py   # /ingest, /retrieve, /articles, /sources route handlers
├── tests/
│   ├── conftest.py                   # Shared pg_engine fixture (session-scoped)
│   ├── test_classifier.py            # Classifier unit tests
│   ├── test_classifier_integration.py
│   ├── test_fetcher.py               # Fetcher unit tests
│   ├── test_fetcher_integration.py
│   ├── test_routes.py                # Route unit tests
│   └── test_routes_integration.py
├── main.py               # FastAPI app, lifespan (DB init + background fetcher)
├── streamlit_app.py      # Streamlit dashboard (calls GET /articles)
├── Dockerfile            # Single image used by both api and ui services
├── docker-compose.yml    # Three services: postgres, api, ui
├── .env                  # Local credentials (gitignored)
├── .env.example          # Credential template (committed)
├── requirements.txt      # Pinned dependencies
└── pytest.ini            # Pytest config (integration marker)
```


## Getting Started

### Prerequisites
- Docker + Docker Compose (recommended)
- *or* Python 3.12, pip, and a running PostgreSQL instance


### Option A: Docker (recommended)

```bash
# Build and start all three services (postgres, api, ui)
docker compose up --build
```

On first start Docker will:
1. Pull the `postgres:16` image and create the database
2. Build the application image and install all dependencies
3. Start the API, it creates tables, seeds the 4 default sources, and begins fetching
4. Start the Streamlit UI once the API is up

| Service | URL |
|---------|-----|
| API | `http://localhost:8000` |
| Swagger UI | `http://localhost:8000/docs` |
| Streamlit dashboard | `http://localhost:8501` |

The HuggingFace model (~300MB) is downloaded on first start and cached in a Docker volume (`hf_cache`), so subsequent starts are near-instant.

To stop: `docker compose down`. To also delete all data: `docker compose down -v`.


### Option B: Local (without Docker)

**Prerequisites:** Python 3.12 and a running PostgreSQL server.

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Create the database in PostgreSQL (one-time)
createdb news
```

**Terminal 1, API server**

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/news uvicorn main:app --reload
```

On startup the app will:
1. Create all tables in the PostgreSQL database (if they don't exist)
2. Seed the 4 default RSS sources into the `sources` table (skipped if already present)
3. Start a background fetcher that polls all sources every 5 minutes
4. Classify and store each article automatically

The API will be available at `http://localhost:8000`.
Interactive API docs (Swagger UI) at `http://localhost:8000/docs`.

**Terminal 2, Streamlit dashboard**

```bash
streamlit run streamlit_app.py
```

The dashboard will open automatically in your browser at `http://localhost:8501`.

**Sidebar controls:**
- **Refresh now:** triggers an immediate fetch and classification cycle
- **Auto-refresh:** toggle to automatically reload the feed every 5 minutes
- **Category filter:** multiselect to show/hide specific categories
- **Source filter:** multiselect derived from sources present in the current article set; updates automatically when new sources produce articles
- **Sort by:** choose between *Final score* (importance × recency, default), *Importance* (classifier score only), or *Most recent* (publication date)
- **Add a news source:** expandable form in the sidebar; enter a name and RSS feed URL to register a new source. The source is validated (feed must return at least one article) and persisted to the database. It will appear in the feed after the next fetch cycle.

**Article cards** show the category emoji, source, time since publication, title (as a clickable link to the original article when a URL is available), a 200-character body snippet, and three scores (importance, recency, final) displayed compactly on the right side of the card.


## API Reference

### `POST /ingest`
Ingest a batch of raw articles for classification and storage.

**Request body:** JSON array of article objects:
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

**Response:** HTTP 200:
```json
{ "status": "ok", "received": 1 }
```


### `GET /retrieve`
Returns all articles that passed the relevance filter, sorted by score descending. Response matches the API contract shape exactly.

**Response:** JSON array:
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


### `GET /articles`
Same filtering and ordering as `/retrieve` but returns the full internal schema including classification fields. Intended for the UI.

**Response:** JSON array with additional fields:
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


### `POST /sources`
Register a new RSS feed source. The feed URL is validated by fetching it, the request is rejected if no articles are returned. Duplicate feed URLs are rejected with HTTP 409.

**Request body:**
```json
{ "name": "BleepingComputer", "feed_url": "https://www.bleepingcomputer.com/feed/" }
```

**Response:** HTTP 201:
```json
{ "status": "ok", "name": "BleepingComputer" }
```

**Error responses:**
- `409 Conflict`, feed URL is already registered
- `422 Unprocessable Entity`, URL did not return any articles


## Technical Decisions

See [TECHNICAL_DECISIONS.md](TECHNICAL_DECISIONS.md) for detailed rationale on framework, database, classification, ranking, and other design choices.


## Database Layer

### `app/database.py`
Sets up the PostgreSQL connection using SQLAlchemy. The connection string is read from the `DATABASE_URL` environment variable (default: `postgresql://postgres:postgres@localhost:5432/news`). Provides:
- `engine`, SQLAlchemy engine bound to the configured database
- `SessionLocal`, session factory; each request gets its own session
- `get_db()`, FastAPI dependency that yields a session and closes it after use

### `app/models.py`
Defines two SQLAlchemy models.

**`Article`:** stores classified news items. Fields:

| Field | Type | Description |
|------------------|-----------------|------------------------------------------------------|
| `id` | String (PK) | ID from the source, not auto-generated |
| `source` | String | e.g. `"reddit"`, `"ars-technica"` |
| `title` | String | Article headline |
| `body` | Text (optional) | Article content |
| `published_at` | DateTime | UTC timestamp from the source |
| `url` | String (optional) | Link to the original article, populated from the RSS `link` field. Stored separately from `id` because some sources (e.g. Tom's Hardware) use non-URL GUIDs as their RSS entry ID. |
| `importance_score` | Float | Weighted score from zero-shot classifier (0–1), stored at fetch time |
| `is_filtered` | Boolean | `True` if article passed the classifier threshold |
| `category` | String | Winning label from the classifier |
| `ingested_at` | DateTime | When the article was received by the system |

**`RSSSourceModel`:** stores registered RSS feed sources. Fields:

| Field | Type | Description |
|------------|----------|--------------------------------------|
| `id` | Integer (PK) | Auto-incremented primary key |
| `name` | String | Source slug used on article records |
| `feed_url` | String (unique) | Full RSS feed URL |
| `added_at` | DateTime | When the source was registered |

Both tables are created automatically at startup via `Base.metadata.create_all()`. The 4 default sources are seeded into `RSSSourceModel` on first startup by `seed_default_sources()` in `fetcher.py`.

### `app/schemas.py`
Pydantic schemas for request/response validation:
- `ArticleIngest`, validates incoming data from `POST /ingest`
- `ArticleResponse`, shapes outgoing data from `GET /retrieve`
- `SourceCreate`, validates incoming data from `POST /sources` (`name`, `feed_url`)

`ArticleIngest` and `ArticleResponse` match the API contract shape: `id`, `source`, `title`, `body`, `published_at`.


## Fetcher Layer

### `app/fetcher.py`
Fetches articles from all registered RSS sources, classifies them, and persists them to the database. Designed for modularity, adding a new source requires only a new subclass with two attributes.

**Key components:**

- `BaseSource`, abstract base class. Every source must implement `fetch() -> List[ArticleIngest]`.
- `RSSSource(BaseSource)`, shared RSS parsing logic (GUID extraction, HTML stripping, date parsing, error handling). The RSS `link` field is stored separately as `url`, distinct from `id`, because some sources use non-URL GUIDs as their RSS entry identifier (e.g. Tom's Hardware uses random strings; Reddit uses `t3_<post_id>` formatted URLs that don't resolve to the article).
- `_DEFAULT_SOURCES`, a list of `(name, feed_url)` tuples for the 4 built-in sources.
- `seed_default_sources(db_factory)`, inserts the default sources into the `sources` DB table on first startup. Subsequent calls are no-ops (each URL has a unique constraint). Called from `main.py` after `create_all()`.
- `FetcherService`, runs an async background loop every 5 minutes. `_fetch_all` loads **all** sources from the `sources` table at the start of every cycle (default + user-added), builds an `RSSSource` instance for each, and calls `classify_and_save()` for every fetched article. No code changes are needed to pick up a newly added source, it is included automatically on the next cycle.

**Design decisions:**
- **All sources in the DB:** there is no distinction between built-in and user-added sources at runtime. Both are rows in the `sources` table and are treated identically by the fetcher. Adding a source via the UI and adding it to `_DEFAULT_SOURCES` produce exactly the same outcome.
- Errors in one source are logged and skipped, other sources are unaffected.
- **Skip-if-unchanged:** before running ML inference, `classify_and_save()` checks whether an article with the same ID already exists in the DB with identical `title` and `body`. If so, the existing record is returned immediately and classification is skipped entirely. If the content has changed, the article is re-classified and updated. This avoids redundant ML inference on every fetch cycle for articles that haven't changed.
- `_fetch_all` runs inside `loop.run_in_executor(None, ...)` so the blocking RSS + ML work happens in a thread pool and never stalls FastAPI's event loop. Incoming requests are handled normally while a fetch cycle is in progress.
- A 5-second delay is inserted before the first fetch cycle at startup, giving the server time to finish initialising and become reachable before the first (potentially slow) classification run begins.


## Classifier Layer

### `app/classifier.py`
Scores each article for relevance to IT managers and persists the result to the database. Called by both the background fetcher and the `/ingest` route.

**Importance score:**
The zero-shot model returns confidence scores across all labels (summing to 1.0). Each confidence is multiplied by its label weight, and the results are summed to produce `importance_score`:

```
importance_score = sum(confidence[label] × weight[label])
```

Since confidences sum to 1.0, the score is naturally bounded:
- `0.2`, article is entirely general tech news
- `1.0`, article is entirely a cybersecurity incident or outage

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
- **Title + body snippet** is fed to the classifier. The article title alone is often insufficient to distinguish real news from community forum posts, a Reddit post titled *"HELP PLEASE! Had my first real email compromise incident this week"* is indistinguishable from a news headline without the body context. The first 300 characters of the body are appended to the title before classification, giving the model enough context to detect the conversational tone of forum posts. 300 characters was chosen as a balance between signal and inference speed.
- **Lazy model loading:** the model is loaded on the first classification call, keeping app startup fast.
- **Skip-if-unchanged:** `classify_and_save()` checks for an existing DB record with the same ID before classifying. If `title` and `body` are identical, classification is skipped and the existing record is returned. If the content has changed, the article is re-classified and the record updated. `title + body` was chosen as the change signal since they are the only fields that affect the classification result. The zero-shot model is deterministic at inference time (transformer models run in eval mode with dropout disabled, so identical inputs always produce identical outputs), so strictly speaking re-classifying unchanged content would yield the same scores. The skip-if-unchanged check is a precautionary measure that also avoids unnecessary CPU overhead on each fetch cycle.
- **Failure handling:** if classification fails, the article is still saved with null scores and `is_filtered = False`. No data is lost.
- **Shared singleton:** a single `classifier` instance is imported by both the fetcher and the `/ingest` route, so the model is only loaded once.
- **Category** is the label with the highest weighted score, used for display in the UI.
- **Synchronous `/ingest`, acknowledgment only after classification and DB write:** the `/ingest` endpoint blocks until every article in the batch has been classified and committed to the database before returning `{"status": "ok"}`. This is a deliberate consequence of the single-table PoC design: because there is no landing zone for raw articles, the database only ever holds fully processed records. If the endpoint returned immediately (fire-and-forget) and classification then failed silently in the background, the caller would have no way to know the data was never actually stored, the `"ok"` response would be misleading. By blocking, the acknowledgment is a genuine confirmation that the data is in the database and queryable. In a production system with a two-table design (raw landing table + processed table), the `/ingest` endpoint could return as soon as the raw records are written to the landing table, which is fast because it requires no ML inference. If classification later fails for a batch, the raw records are still available in the landing table and can be reprocessed at any time, so nothing is lost.

## Testing

The project separates **unit tests** (fast, no network, no model) from **integration tests** (real HTTP calls or real ML model).

### How to run the tests

#### Step 1: Activate the virtual environment

```bash
# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

#### Step 2: Start a PostgreSQL instance for tests

The route tests need a live PostgreSQL database. The easiest way is a one-liner Docker container:

```bash
docker run -d --name pg_test \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=test_news \
  -p 5432:5432 \
  postgres:16
```

Wait a few seconds for it to be ready, then verify:

```bash
docker exec pg_test pg_isready -U postgres
# expected output: /var/run/postgresql:5432 - accepting connections
```

> If you already have PostgreSQL running locally, just create a `test_news` database: `createdb test_news`

#### Step 3: Set the test database URL

```bash
# Windows (PowerShell)
$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/test_news"

# Windows (CMD)
set TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test_news

# macOS/Linux
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test_news
```

#### Step 4: Run unit tests (fast, ~1s, no network, no ML model)

```bash
pytest -m "not integration" -v
```

Expected: **55 passed**

#### Step 5: Run integration tests (slow, ~60s, downloads ML model on first run)

```bash
pytest -m integration -v
```

Expected: **18 passed**
> The first run downloads the ~300MB ML model. Subsequent runs use the local cache and take ~60s.

#### Step 6: Run the full test suite

```bash
pytest -v
```

Expected: **73 passed**

#### Step 7: Clean up the test container

```bash
docker rm -f pg_test
```


### Test command reference

| Command                                                | What it runs                                          |
|--------------------------------------------------------|-------------------------------------------------------|
| `pytest tests/test_fetcher.py -v`                     | Fetcher unit tests, mocked feedparser                |
| `pytest tests/test_routes.py -v`                      | Route unit tests, mocked classifier, PostgreSQL DB   |
| `pytest tests/test_classifier.py -v`                  | Classifier unit tests, mocked ML pipeline            |
| `pytest -m "not integration" -v`                      | All unit tests (fast, no network, no model)           |
| `pytest tests/test_fetcher_integration.py -v`         | Fetcher integration, hits real RSS feeds             |
| `pytest tests/test_routes_integration.py -v`          | Route integration, real classifier, PostgreSQL DB    |
| `pytest tests/test_classifier_integration.py -v`      | Classifier integration, loads real ML model          |
| `pytest -m integration -v`                            | All integration tests                                 |
| `pytest -v`                                           | Full test suite (unit + integration)                  |

### Unit tests

**`tests/test_fetcher.py`:** mocks `feedparser`, no HTTP calls. Covers:
- `strip_html`, `parse_date`, `RSSSource.fetch()`

**`tests/test_classifier.py`:** mocks the ML pipeline. Covers:
- `_compute_recency`, `_compute_importance`, `classify_and_save`, skip-if-unchanged
- `classify_and_save` tests no longer assert on `recency_score` or `final_score`, those are not stored, only `importance_score`, `category`, and `is_filtered` are verified
- Score arrays in `_compute_importance` tests have 6 elements, one per label including "IT community discussion or advice request". Previously they had 5, causing `zip` to silently drop the new label from the weighted sum
- `TestSkipIfUnchanged` covers all four branches: unchanged article (skips inference), title changed (re-classifies), body changed (re-classifies), no existing record (classifies normally)

**`tests/test_routes.py`:** mocks the classifier, uses a PostgreSQL test database. Covers:
- `POST /ingest`, acknowledgment, batch count, validation errors, classifier called per article
- `GET /retrieve`, filtering, ordering, contract response shape (no classification fields leaked)
- `GET /articles`, full schema with classification fields, consistent ordering with `/retrieve`
- Sort order tests use `importance_score` and `published_at=now` (recency ≈ 1.0) to control ranking, since `final_score` is not stored and ordering happens in Python at request time
- Classification field tests assert that `recency_score` and `final_score` are present and within `(0, 1]` rather than exact values, since they are computed dynamically at request time

#### Test isolation with PostgreSQL

All route tests share a single session-scoped PostgreSQL engine (created once in `conftest.py`). Tables are created at the start of the test session and dropped at the end. Each individual test deletes all rows after it runs, giving per-test isolation without the overhead of recreating the schema for every test.

### Integration tests

**`tests/test_fetcher_integration.py`:** real HTTP requests to each RSS feed. Verifies each source returns valid articles with all required fields.

**`tests/test_classifier_integration.py`:** loads the actual `valhalla/distilbart-mnli-12-3` model. Verifies relevant headlines pass the filter and irrelevant ones don't.

**`tests/test_routes_integration.py`:** real classifier + PostgreSQL test database. Tests the full ingest → classify → retrieve pipeline end-to-end, including determinism and correct filtering.

> **Note:** Integration tests require an active internet connection (fetcher) or will trigger model loading (~300MB download on first run, cached after). Run `pytest -m "not integration"` to skip them.


## Potential Improvements

### Classifier
- **Weighted final score formula:** the current formula `final_score = importance_score × recency_score` gives recency equal multiplicative power. A weighted sum like `0.7 × importance + 0.3 × recency` would let importance dominate ranking more explicitly, keeping older but highly relevant articles more visible.
- **Longer body context:** the classifier currently uses the first 300 characters of the body. Using more (e.g. 512 tokens worth) would give the model more signal, at the cost of slower inference.
- **Re-classification without DB wipe:** changing the classifier (new labels, new weights) currently requires deleting the database and re-fetching everything. A `/reclassify` endpoint that reruns the classifier on all stored articles without re-fetching would make iteration faster.
- **Confidence threshold per label:** instead of a single global importance threshold, each label could have its own minimum confidence to pass, giving finer control over which types of events are surfaced.

### Data sources
- **Reddit r/sysadmin:** even with the new "IT community discussion" category, some Reddit posts still slip through because their titles resemble news headlines. This source could be removed entirely, or a higher per-source confidence threshold could be applied to reduce noise.
- **More sources:** adding sources like BleepingComputer, Dark Reading, or vendor security bulletins would improve coverage of cybersecurity and software vulnerability news specifically.
- **Source removal from the UI:** sources can currently be added via the UI but not removed. A delete button per source row would let the IT manager disable noisy sources without touching the database directly.
- **Full article scraping:** RSS bodies are often truncated. Scraping the full article text would give the classifier much richer context for difficult cases.

### Database
- **Two-table design:** separate raw ingestion from classified storage (see the existing note in the Database section). This would allow re-classification without data loss and make the ingest endpoint faster.
- **Retention policy:** old articles accumulate indefinitely. A scheduled cleanup job deleting articles older than N days would keep the database from growing unboundedly.

### API & infrastructure
- **Authentication:** the API currently has no authentication. Any process that can reach port 8000 can ingest or retrieve articles. Adding an API key header would be the minimal production requirement.
- **Alerting:** for a real IT manager use case, high-priority articles (e.g. `importance_score > 0.9`) could trigger a notification (email, Slack, PagerDuty) rather than waiting for the user to check the dashboard.
- **Pagination:** the `/retrieve` and `/articles` endpoints currently return all matching articles. As the database grows, adding `limit` and `offset` query parameters would keep response sizes manageable.

### UI
- **Replace Streamlit with a proper frontend:** as noted in the framework section, Streamlit rerenders the entire page on every interaction and does not scale to multiple users. A React or Vue frontend calling the FastAPI directly would provide real-time updates, better performance, and full UI flexibility.
- **Read/unread state:** the dashboard currently shows all articles on every load. Tracking which articles the user has already seen and only surfacing new ones would make the feed much more actionable.


## Bonus Question: Evaluating Efficiency and Correctness

### Correctness

Correctness of the filtering process means two things: **precision** (articles that passed the filter are genuinely relevant) and **recall** (relevant articles are not being dropped).

**What was done in this project:**
- Two analysis notebooks (`analysis.ipynb`, `analysis_new_category.ipynb`) were used to evaluate the classifier on real fetched data. They cover score distributions, per-category article samples, borderline cases (articles near the 0.5 threshold), and pass rates per source.
- Manual inspection revealed a systematic error: Reddit r/sysadmin posts were being misclassified as high-priority news because the model had no appropriate bucket for community forum content. This led to the addition of the "IT community discussion or advice request" label (weight 0.15), which brought those posts below the filter threshold. This is an example of **qualitative error analysis** driving a classifier improvement.
- The integration test suite (`test_classifier_integration.py`) provides a lightweight automated correctness check: it loads the real model and asserts that known high-relevance headlines pass the filter and known irrelevant headlines do not.

**What a more rigorous evaluation would look like:**
- **Labelled test set:** the most reliable method is a held-out set of articles manually labelled as relevant/irrelevant by a domain expert (an IT manager). Precision and recall can then be computed exactly, and the threshold can be tuned to the desired operating point on the precision-recall curve.
- **Confusion matrix per category:** beyond binary pass/fail, checking whether the assigned category is correct gives a clearer picture of where the model is weakest. A category that frequently "catches" articles from wrong sources indicates the label definition or weight needs adjustment.
- **Threshold sensitivity analysis:** plotting pass rate vs. threshold value shows how aggressively the filter behaves and helps identify a threshold that minimises both false positives (noise) and false negatives (missed events).

### Efficiency

Efficiency covers two dimensions: **inference speed** (how fast articles are classified) and **retrieval quality** (how well the ranking serves the user).

**Inference speed:**
- The current model processes one article at a time on CPU. Measured on a standard laptop, this is roughly 0.5–1.5 seconds per article depending on text length. For a fetch cycle of ~120 articles every 5 minutes, this means classification completes in 1–3 minutes, well within the 5-minute polling interval.
- If throughput became a bottleneck, batching multiple articles in a single model call (transformers pipelines support batching natively) or switching to a smaller distilled model would be the first levers to pull.

**Ranking quality:**
- The `final_score = importance_score × recency_score` formula means a highly important article published 48 hours ago scores the same as a moderately important article published just now. Whether this trade-off is correct depends on the use case.
- A practical way to evaluate ranking quality is **position-weighted user feedback**: if an IT manager consistently opens articles ranked 5–10 rather than 1–4, it suggests the ranking is not well-calibrated. Click-through position data, even from a single user over a few weeks, would surface systematic ranking errors without needing a formal labelling exercise.
