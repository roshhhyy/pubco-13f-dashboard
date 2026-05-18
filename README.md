# 13F Holdings Dashboard

Tab-based dashboard for tracking SEC Form 13F-HR filings across multiple
institutional managers. Shows current quarter holdings with quarter-over-quarter
deltas vs. the previous two quarters.

Default filers: Warren Buffett (Berkshire Hathaway), Bill Ackman (Pershing Square),
Leopold Aschenbrenner (Situational Awareness LP).

## Run locally

```
python3 scripts/fetch_13f.py   # pulls latest 3 quarters per filer from EDGAR
open index.html                # or serve via `python3 -m http.server`
```

## Streamlit version

```
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Adding a filer

Edit the `FILERS` list in `scripts/fetch_13f.py`, add an entry with the
display name, CIK, and the three most recent 13F-HR accession numbers
(newest first). Re-run the script and reload the page.

The dashboard's `+ Add` button generates a ready-to-paste snippet for you.

## Data source

All filings are pulled directly from SEC EDGAR via the public web archive.
Raw XML is cached under `data/raw/<accession>/` for verifiability.
