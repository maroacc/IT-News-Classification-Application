import time
from datetime import datetime, timezone

import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

API_URL = "http://localhost:8000/articles"
FETCH_URL = "http://localhost:8000/fetch"
HEALTH_URL = "http://localhost:8000/health"
SOURCES_URL = "http://localhost:8000/sources"
REFRESH_INTERVAL = 300  # seconds — matches fetcher interval

CATEGORIES = [
    "cybersecurity incident or data breach",
    "system outage or service disruption",
    "critical software bug or vulnerability",
    "software release or patch",
    "general technology news",
    "IT community discussion or advice request",
]

CATEGORY_EMOJI = {
    "cybersecurity incident or data breach":     "🔴",
    "system outage or service disruption":       "🟠",
    "critical software bug or vulnerability":    "🟡",
    "software release or patch":                 "🔵",
    "general technology news":                   "⚪",
    "IT community discussion or advice request": "💬",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def check_health() -> str:
    """
    Returns 'ready', 'loading', or 'unreachable'.
    'loading' means the API is up but the ML model hasn't finished loading yet.
    """
    try:
        response = requests.get(HEALTH_URL, timeout=5)
        response.raise_for_status()
        return response.json().get("status", "unreachable")
    except requests.exceptions.ConnectionError:
        return "unreachable"
    except Exception:
        return "unreachable"


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
        response = requests.get(API_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
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
# Health check — poll until API is reachable and model is loaded
# ─────────────────────────────────────────────────────────────────────────────

health = check_health()

if health in ("unreachable", "loading"):
    msg = (
        "Waiting for the server to start…"
        if health == "unreachable"
        else "ML model is loading, this takes ~60s on first run…"
    )
    st.info(msg)
    time.sleep(2)
    st.rerun()

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

    if st.button("Refresh now", icon=":material/refresh:", use_container_width=True):
        with st.spinner("Fetching latest articles..."):
            trigger_fetch()
        st.rerun()

    last_updated = datetime.fromtimestamp(st.session_state.last_refresh).strftime("%H:%M:%S")
    st.caption(f"Last updated: {last_updated}")

    auto_refresh = st.toggle("Auto-refresh (5 min)", value=True)

    st.divider()
    with st.expander("Add a news source", icon=":material/add:"):
        with st.form("add_source_form"):
            new_name = st.text_input("Source name", placeholder="e.g. BleepingComputer")
            new_url  = st.text_input("RSS feed URL", placeholder="https://...")
            submitted = st.form_submit_button("Add source", use_container_width=True)
            if submitted:
                if new_name and new_url:
                    try:
                        resp = requests.post(SOURCES_URL,
                                             json={"name": new_name, "feed_url": new_url},
                                             timeout=15)
                        if resp.status_code == 201:
                            with st.spinner(f"Fetching articles from '{new_name}'..."):
                                trigger_fetch()
                            st.rerun()
                        else:
                            st.error(resp.json().get("detail", "Failed to add source."))
                    except requests.exceptions.ConnectionError:
                        st.error("Cannot reach the API.")
                else:
                    st.warning("Both name and URL are required.")

st.title("📡 IT News Feed")

# ─────────────────────────────────────────────────────────────────────────────
# Filters + sort — inline, above the article list
# ─────────────────────────────────────────────────────────────────────────────

available_sources = sorted({a["source"] for a in articles}) if articles else []

col_cat, col_src, col_kw, col_sort = st.columns([3, 2, 2, 2])

with col_cat:
    selected_categories = st.multiselect(
        "Category",
        options=CATEGORIES,
        default=CATEGORIES,
    )

with col_src:
    selected_sources = st.multiselect(
        "Source",
        options=available_sources,
        default=available_sources,
    )

with col_kw:
    keyword = st.text_input("Keyword", placeholder="Search titles & body…")

with col_sort:
    sort_by = st.radio(
        "Sort by",
        options=["Final score", "Importance", "Most recent"],
    )

# ─────────────────────────────────────────────────────────────────────────────
# Filter & sort
# ─────────────────────────────────────────────────────────────────────────────

kw = keyword.lower()
filtered = [
    a for a in articles
    if (a.get("category") in selected_categories or not selected_categories)
    and (a.get("source") in selected_sources or not selected_sources)
    and (not kw or kw in (a.get("title") or "").lower() or kw in (a.get("body") or "").lower())
]

if sort_by == "Importance":
    filtered.sort(key=lambda a: a.get("importance_score") or 0.0, reverse=True)
elif sort_by == "Most recent":
    filtered.sort(key=lambda a: a.get("published_at") or "", reverse=True)
# "Final score" preserves the API order (final_score desc)

if filtered:
    most_recent_str = max(a.get("published_at") or "" for a in filtered)
    age_label = time_ago(most_recent_str) if most_recent_str else "—"
else:
    age_label = "—"

st.caption(f"**{len(filtered)}** articles &nbsp;·&nbsp; most recent: **{age_label}**")
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
        importance_score = float(article.get("importance_score") or 0.0)
        recency_score = float(article.get("recency_score") or 0.0)
        final_score = float(article.get("final_score") or 0.0)
        published_at = article.get("published_at") or ""

        url = article.get("url") or ""
        title_md = f"[{title}]({url})" if url.startswith("http") else title

        with st.container():
            left, right = st.columns([5, 1])
            with left:
                st.markdown(
                    f"{emoji} **{category}** &nbsp;·&nbsp; "
                    f"`{source}` &nbsp;·&nbsp; *{time_ago(published_at)}*"
                )
                st.markdown(f"### {title_md}")
                if snippet:
                    st.caption(snippet)
            with right:
                st.caption(
                    f"Imp &nbsp;`{importance_score:.2f}`  \n"
                    f"Rec &nbsp;`{recency_score:.2f}`  \n"
                    f"Final `{final_score:.2f}`"
                )
            st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Auto-refresh — sleep then rerun (page is already rendered above)
# ─────────────────────────────────────────────────────────────────────────────

if auto_refresh:
    time.sleep(REFRESH_INTERVAL)
    st.rerun()
