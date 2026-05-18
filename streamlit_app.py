"""Streamlit wrapper for the 13F dashboard.

The dashboard is a self-contained HTML/JS file (index.html). This wrapper
inlines the data and embeds the page via st.components.v1.html so it can
run on Streamlit Community Cloud.

To refresh the underlying data, run `python scripts/fetch_13f.py` locally
and commit the regenerated data/holdings.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "index.html"
DATA_PATH = ROOT / "data" / "holdings.json"

st.set_page_config(
    page_title="13F Holdings Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Hide Streamlit chrome so the dashboard fills the viewport.
st.markdown(
    """
    <style>
      header[data-testid="stHeader"] { display: none; }
      .block-container { padding: 0 !important; max-width: 100% !important; }
      [data-testid="stAppViewBlockContainer"] { padding: 0 !important; }
      footer { display: none !important; }
      #MainMenu { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_assets() -> tuple[str, dict]:
    # No cache: file reads are fast and caching here once burned us by serving
    # a stale HTML for an hour after a deploy. The container is ephemeral
    # anyway; re-reading per request is negligible.
    html = HTML_PATH.read_text()
    data = json.loads(DATA_PATH.read_text())
    return html, data


def main() -> None:
    if not HTML_PATH.exists() or not DATA_PATH.exists():
        st.error(
            "Dashboard assets missing. Run `python scripts/fetch_13f.py` to "
            "regenerate `data/holdings.json`, then commit and push."
        )
        return

    html, data = load_assets()

    # Inline the data so the dashboard works inside Streamlit's iframe
    # (sibling-path <script src> wouldn't resolve here).
    inline = f"<script>window.HOLDINGS_DATA = {json.dumps(data)};</script>"
    html = html.replace('<script src="data/holdings.js"></script>', inline)

    components.html(html, height=2400, scrolling=True)

    generated = data.get("generated_at", "unknown")
    try:
        dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        st.sidebar.caption(f"Data generated {generated} ({age_hours:.0f}h ago)")
    except Exception:
        st.sidebar.caption(f"Data generated {generated}")
    # Build marker — if you see this commit in the sidebar, you're on the latest deploy.
    st.sidebar.caption("Build: clickable-quarters")
    st.sidebar.caption("Refresh data locally with `python scripts/fetch_13f.py` and push.")


if __name__ == "__main__":
    main()
