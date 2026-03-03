# Technical Decisions

This document explains the key design decisions and trade-offs made in building this system.


## Architecture

### Framework: FastAPI + Streamlit
FastAPI handles the REST API (`/ingest`, `/retrieve`) due to its native async support, automatic request validation via Pydantic, and auto-generated docs. Streamlit is used for the UI, it allows building a functional web dashboard in pure Python with minimal overhead.

**Streamlit is suitable for this PoC but not for production with multiple users.** Key limitations:

- **Full page re-render on every interaction:** Streamlit has no concept of partial updates. Any filter change, button click, or auto-refresh reruns the entire Python script from top to bottom and redraws the whole page. For a single user this is acceptable; for many concurrent users it becomes slow and resource-heavy.
- **No true multi-user session isolation:** Streamlit's session state is per-browser-tab, but the server runs a single Python process. Under concurrent load, blocking operations (like the auto-refresh sleep) affect all sessions.
- **Limited UI customisation:** layout, styling, and interactivity are constrained by what Streamlit exposes. Building a production-grade newsfeed UI with real-time updates, pagination, or user preferences would require a proper frontend framework (React, Vue, etc.).
- **Not designed for horizontal scaling:** Streamlit apps are stateful and tied to a single process, making them hard to scale behind a load balancer.

For the intended use case, **a single IT manager checking the feed:** these limitations are irrelevant. Streamlit delivers a functional, readable dashboard with minimal code, which is exactly what a PoC requires.

### Database: PostgreSQL + SQLAlchemy ORM
PostgreSQL is used as the database backend, running as a dedicated service in Docker. SQLAlchemy ORM handles all database interaction without raw SQL. The connection string is injected via the `DATABASE_URL` environment variable, keeping credentials out of the codebase. Switching to a different database engine (e.g. MySQL) would be a one-line change to that variable.

An embedded database (e.g. SQLite) would have been simpler to set up, but was not used because the background fetcher and the `/ingest` endpoint write concurrently, and embedded databases serialise writes with a file lock that would cause errors under that load. A client/server database also fits naturally into Docker Compose as a dedicated service, whereas an embedded file would need careful volume management to survive container restarts.

**Single table design (PoC decision):** A single `articles` table stores all news items, already classified. Articles are classified and scored before being written to the database, meaning only enriched, processed records ever land in storage. This keeps the schema simple and queries fast for a proof of concept.

In a production scenario, a better approach would be a **two-table design**:
- A **landing table** receives raw articles immediately on ingestion, with no processing delay. This ensures data is never lost even if classification fails, and allows the ingest endpoint to respond fast.
- A **processed table** receives articles after classification, enriched with scores and category.
- The landing table can be cleaned up after a configurable retention period (e.g. delete records older than 7 days) to prevent unbounded growth.

This separation also makes it easier to reprocess articles if the classifier changes, since the raw data is always available.

### `/retrieve` scope: all filtered articles
Both articles fetched from RSS sources and articles injected via `/ingest` go through the same `classify_and_save()` pipeline and are stored in the same table. The `/retrieve` endpoint returns **all** articles marked `is_filtered = True`, regardless of their origin.

This is a deliberate design choice: the system is a unified newsfeed, the test harness articles and the live RSS articles are treated equally. The spec says `/retrieve` should return "only the events your system decided to keep", without restricting by source.

One implication: since the background fetcher continuously adds new articles, the result set of `/retrieve` can grow between calls. The **ordering is always deterministic** (scores are fixed at ingestion time), but **membership may grow** as new articles arrive. This is expected behaviour for a live newsfeed system.


## Classification Pipeline

### Classification: Zero-shot (`valhalla/distilbart-mnli-12-3`)
No labelled dataset was provided for this task, making supervised training impractical. Even if one were available, collecting a dataset large and diverse enough to outperform modern pre-trained models would require significant time and resources. Zero-shot models have advanced to the point where they generalise remarkably well across domains out of the box, making them the pragmatic and effective choice here.

Zero-shot classification allows us to define meaningful IT-manager-relevant categories (e.g. "system outage", "cybersecurity incident") without needing any labelled training data. The `valhalla/distilbart-mnli-12-3` model is a distilled version of BART-large-MNLI, a good balance between accuracy and speed for local/CPU use.

The classifier assigns a weighted importance score (0–1) based on predefined labels and their relevance to IT managers:

| Label                                       | Weight |
|---------------------------------------------|--------|
| `cybersecurity incident or data breach`     | 1.0    |
| `system outage or service disruption`       | 1.0    |
| `critical software bug or vulnerability`    | 0.9    |
| `software release or patch`                 | 0.5    |
| `general technology news`                   | 0.2    |
| `IT community discussion or advice request` | 0.15   |

The sixth label (`IT community discussion or advice request`) was added after analysis revealed that Reddit r/sysadmin posts, which are forum discussions, not news articles, were being forced into high-weight categories like "system outage" and passing the filter incorrectly. A dedicated low-weight label (0.15, below the 0.5 threshold) gives the model a correct bucket for community content, causing it to be filtered out automatically.

### Model loading: eager, background thread

The ML model (~300MB) is loaded **eagerly at startup** rather than lazily on the first classification request. This avoids an unexpected multi-second stall on the first `/ingest` or `/fetch` call after the server starts.

Loading happens in a **daemon background thread** (`threading.Thread(target=classifier.load, daemon=True).start()`) so the server becomes reachable within seconds. The model finishes loading in parallel, typically ~60s on first run (download + load), near-instant on subsequent runs (cached locally by HuggingFace).

A public `load()` method was added to `ClassifierService` (calling the existing internal `_get_pipeline()`) along with an `is_ready` property, so the startup logic can interact with a clean public API without reaching into private internals.

**`GET /health`** exposes readiness to callers. Returns `{"status": "loading"}` while the model is initialising, and `{"status": "ready"}` once all endpoints are fully operational.

The Streamlit dashboard polls `/health` every 2 seconds on startup and shows a *"ML model is loading…"* spinner instead of a confusing connection error. Once `"ready"` is returned, the dashboard fetches and renders articles normally.

### Ranking: Importance × Recency
Each article is ranked by `final_score = importance_score × recency_score`, where:
- `importance_score` comes from the weighted zero-shot classifier output, computed **at fetch time** and stored in the database
- `recency_score = e^(-λ * hours_since_published)`, computed **at retrieve time**, so it always reflects the article's true age at the moment of the request

`importance_score` is the only score persisted. `recency_score` and `final_score` are computed fresh on every call to `/retrieve` and `/articles` and injected into the response. This means the ranking automatically degrades older articles over time without any reprocessing, an article fetched yesterday will rank lower today than it did yesterday.

### Filter Pass Rate by Source
After the first fetch cycle, the classifier accepted the following proportions per source:

| Source | Fetched | Passed filter | Pass rate |
|---|---|---|---|
| The Hacker News | 50 | 48 | 96% |
| Tom's Hardware | 26 | 17 | 65% |
| Reddit r/sysadmin | 25 | 23 | 92% |
| Ars Technica | 20 | 15 | 75% |
| **Total** | **121** | **103** | **85%** |

These rates reflect how well each source aligns with IT manager relevance. The Hacker News and Reddit r/sysadmin score very high because their content is almost entirely security incidents, outages, and critical bugs, exactly the categories with the highest label weights. Tom's Hardware covers general hardware reviews and product announcements alongside IT-relevant content, so more articles fall below the threshold. Ars Technica similarly mixes general technology coverage with IT-critical reporting.

This also serves as a sanity check on the classifier: a source like The Hacker News passing 96% makes intuitive sense, while a general tech publication passing everything would indicate the filter is too permissive.


## Data Ingestion

### News Sources: RSS feeds
All sources are fetched via RSS, no API credentials required. Sources are stored in the `sources` database table and loaded at the start of every fetch cycle. The 4 defaults are seeded on startup; additional sources can be added at runtime via `POST /sources` or through the "Add a news source" form in the Streamlit sidebar.

| Source              | Feed                                                        |
|---------------------|-------------------------------------------------------------|
| Reddit r/sysadmin   | `https://www.reddit.com/r/sysadmin.rss`                    |
| Ars Technica        | `https://feeds.arstechnica.com/arstechnica/technology-lab` |
| The Hacker News     | `https://feeds.feedburner.com/TheHackersNews`               |
| Tom's Hardware      | `https://www.tomshardware.com/feeds/all`                    |

### Fetch Interval: Every 5 minutes
The background fetcher runs as a FastAPI startup task, polling all sources every 5 minutes. This provides near real-time updates while avoiding excessive load on the sources.

### RSS Feed Snapshot Model and Coverage
RSS feeds are static XML files served by the publisher. Each fetch returns a **snapshot** of whatever articles the site currently exposes, typically their 20–50 most recent items. There is no pagination and no way to request articles beyond that window. The number of articles per fetch is entirely controlled by the publisher:

| Source | Articles exposed per fetch |
|---|---|
| The Hacker News | ~50 |
| Tom's Hardware | ~25 |
| Reddit r/sysadmin | ~25 |
| Ars Technica | ~20 |

Each fetch cycle, new articles that have appeared since the last fetch will be present in the snapshot while old ones will have dropped off. As long as new articles appear slower than the feed rotates, no articles are missed. For IT news sites, a few articles per hour is typical, well within a 5-minute polling interval.

**What could be missed:** if a site published articles faster than the feed window rotates between fetches, the oldest items could drop off before we catch them. In practice this does not happen for IT news sources. A more robust solution would track the last seen article ID per source and alert if gaps are detected, but this is unnecessary overhead for the current use case.
