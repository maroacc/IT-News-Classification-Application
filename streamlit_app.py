import time
from datetime import datetime, timezone

import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

API_URL = "http://localhost:8000/articles"
FETCH_URL = "http://localhost:8000/fetch"
REFRESH_INTERVAL = 300  # seconds — matches fetcher interval

CATEGORIES = [
    "cybersecurity incident or data breach",
    "system outage or service disruption",
    "critical software bug or vulnerability",
    "software release or patch",
    "general technology news",
]

SOURCES = [
    "reddit-sysadmin",
    "ars-technica",
    "the-hacker-news",
    "toms-hardware",
]

CATEGORY_EMOJI = {
    "cybersecurity incident or data breach":  "🔴",
    "system outage or service disruption":    "🟠",
    "critical software bug or vulnerability": "🟡",
    "software release or patch":              "🔵",
    "general technology news":                "⚪",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def trigger_fetch() -> bool:
    """Call POST /fetch to run an immediate fetch+classify cycle. Returns True on success."""
    try:
        response = requests.post(FETCH_URL, timeout=120)
        response.raise_for_status()
        return True
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the API at http://localhost:8000.")
        return False
    except Exception as e:
        st.error(f"Fetch failed: {e}")
        return False


def get_articles() -> list[dict]:
    """Fetch articles from the API. Returns an empty list and shows an error on failure."""
    try:
        response = requests.get(API_URL, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        st.error(
            "Cannot reach the API at http://localhost:8000. "
            "Start it with: `uvicorn main:app --reload`"
        )
        return []
    except Exception as e:
        st.error(f"Failed to fetch articles: {e}")
        return []


def time_ago(published_at: str) -> str:
    """Convert a UTC ISO datetime string to a human-readable 'X ago' label."""
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Page config  (must be the first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="IT News Feed",
    page_icon="📡",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

# ─────────────────────────────────────────────────────────────────────────────
# Fetch data
# ─────────────────────────────────────────────────────────────────────────────

articles = get_articles()
st.session_state.last_refresh = time.time()

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Controls")

    if st.button("🔄 Refresh now", use_container_width=True):
        with st.spinner("Fetching latest articles..."):
            trigger_fetch()
        st.rerun()

    last_updated = datetime.fromtimestamp(st.session_state.last_refresh).strftime("%H:%M:%S")
    st.caption(f"Last updated: {last_updated}")

    auto_refresh = st.toggle("Auto-refresh (5 min)", value=True)

    st.divider()
    st.subheader("Filters")

    selected_categories = st.multiselect(
        "Category",
        options=CATEGORIES,
        default=CATEGORIES,
    )

    selected_sources = st.multiselect(
        "Source",
        options=SOURCES,
        default=SOURCES,
    )

    st.divider()

    sort_by = st.radio(
        "Sort by",
        options=["Importance (default)", "Most recent"],
    )

# ─────────────────────────────────────────────────────────────────────────────
# Filter & sort
# ─────────────────────────────────────────────────────────────────────────────

filtered = [
    a for a in articles
    if (a.get("category") in selected_categories or not selected_categories)
    and (a.get("source") in selected_sources or not selected_sources)
]

if sort_by == "Most recent":
    filtered.sort(key=lambda a: a.get("published_at") or "", reverse=True)
# "Importance (default)" preserves the API order (final_score desc)

# ─────────────────────────────────────────────────────────────────────────────
# Page title + summary metrics
# ─────────────────────────────────────────────────────────────────────────────

st.title("📡 IT News Feed")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Articles shown", len(filtered))

with col2:
    top_score = max((a.get("final_score") or 0.0 for a in filtered), default=0.0)
    st.metric("Highest score", f"{top_score:.2f}")

with col3:
    if filtered:
        most_recent_str = max(a.get("published_at") or "" for a in filtered)
        age_label = time_ago(most_recent_str) if most_recent_str else "—"
    else:
        age_label = "—"
    st.metric("Most recent", age_label)

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Article cards
# ─────────────────────────────────────────────────────────────────────────────

if not filtered:
    st.info("No articles match your current filters, or the API returned no results.")
else:
    for article in filtered:
        category = article.get("category") or "general technology news"
        emoji = CATEGORY_EMOJI.get(category, "⚪")
        source = article.get("source", "unknown")
        title = article.get("title") or "Untitled"
        body = article.get("body") or ""
        snippet = (body[:200] + "…") if len(body) > 200 else body
        final_score = float(article.get("final_score") or 0.0)
        published_at = article.get("published_at") or ""

        with st.container():
            st.markdown(
                f"{emoji} **{category}** &nbsp;·&nbsp; "
                f"`{source}` &nbsp;·&nbsp; *{time_ago(published_at)}*"
            )
            st.markdown(f"### {title}")
            st.progress(min(final_score, 1.0), text=f"Score: {final_score:.3f}")
            if snippet:
                st.caption(snippet)
            st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh — sleep then rerun (page is already rendered above)
# ─────────────────────────────────────────────────────────────────────────────

if auto_refresh:
    time.sleep(REFRESH_INTERVAL)
    st.rerun()
