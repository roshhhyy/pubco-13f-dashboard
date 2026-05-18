"""
Fetch and parse 13F-HR filings from SEC EDGAR for a set of filers,
compute quarter-over-quarter changes, and write a single JSON dataset
consumed by the dashboard.

The filer list is declared in FILERS below. To add a new filer, append
an entry with display name, CIK, and the three most recent accession
numbers (most recent first). Re-run this script and the dashboard will
automatically pick the new filer up.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

UA = "Research roshun ro@erebor.so"
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "holdings.json"
OUT_JS = ROOT / "data" / "holdings.js"

FILERS = [
    {
        "key": "buffett",
        "name": "Warren Buffett",
        "fund": "Berkshire Hathaway Inc.",
        "cik": "1067983",
        "color": "#c0392b",
        # Most recent first: Q1 2026, Q4 2025, Q3 2025
        "accessions": [
            "0001193125-26-226661",
            "0001193125-26-054580",
            "0001193125-25-282901",
        ],
    },
    {
        "key": "ackman",
        "name": "Bill Ackman",
        "fund": "Pershing Square Capital Management, L.P.",
        "cik": "1336528",
        "color": "#2980b9",
        "accessions": [
            "0001172661-26-002336",
            "0001172661-26-001091",
            "0001172661-25-005039",
        ],
    },
    {
        "key": "aschenbrenner",
        "name": "Leopold Aschenbrenner",
        "fund": "Situational Awareness LP",
        "cik": "2045724",
        "color": "#27ae60",
        "accessions": [
            "0002045724-26-000008",
            "0002045724-26-000002",
            "0002045724-25-000008",
        ],
    },
]


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def accession_to_path(accession: str) -> str:
    return accession.replace("-", "")


def list_filing_files(cik: str, accession: str) -> list[str]:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_to_path(accession)}/"
    html = http_get(base).decode("utf-8", errors="replace")
    files = re.findall(r'href="[^"]+/([^"/]+\.xml)"', html)
    return list(dict.fromkeys(files))


def fetch_filing(cik: str, accession: str) -> dict:
    """Return primary_doc metadata + raw infotable XML string."""
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_to_path(accession)}/"
    files = list_filing_files(cik, accession)
    primary = "primary_doc.xml"
    info_candidates = [f for f in files if f != primary]
    if not info_candidates:
        raise RuntimeError(f"no info table for {accession}")
    # Some filings (rare) include extra XML beyond the info table. Pick the largest by
    # fetching all candidates — but practically, the first non-primary XML is the table.
    info_name = info_candidates[0]

    primary_xml = http_get(base + primary).decode("utf-8", errors="replace")
    info_xml = http_get(base + info_name).decode("utf-8", errors="replace")

    # Cache locally so re-runs are fast / verifiable.
    cache_dir = RAW / accession
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / primary).write_text(primary_xml)
    (cache_dir / info_name).write_text(info_xml)

    return {"primary_xml": primary_xml, "info_xml": info_xml, "info_name": info_name}


# ---- XML parsing ---------------------------------------------------------

def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_primary(primary_xml: str) -> dict:
    root = ET.fromstring(primary_xml)
    out = {}
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        if tag == "periodOfReport" and elem.text:
            out["period"] = elem.text.strip()  # MM-DD-YYYY
        elif tag == "tableEntryTotal" and elem.text:
            out["holdings_count"] = int(elem.text.strip())
        elif tag == "tableValueTotal" and elem.text:
            out["table_value_total"] = int(elem.text.strip())
        elif tag == "name" and "filer" not in out and elem.text:
            out["filer_name"] = elem.text.strip()
    return out


def parse_infotable(info_xml: str) -> list[dict]:
    root = ET.fromstring(info_xml)
    rows: list[dict] = []
    for info in root.iter():
        if _strip_ns(info.tag) != "infoTable":
            continue
        record = {
            "issuer": None,
            "class": None,
            "cusip": None,
            "value": 0,         # USD (post-2023: actual dollars per SEC amendment)
            "shares": 0,
            "share_type": None,
            "put_call": None,
            "discretion": None,
            "manager": None,
        }
        for child in info.iter():
            tag = _strip_ns(child.tag)
            text = (child.text or "").strip()
            if tag == "nameOfIssuer":
                record["issuer"] = text
            elif tag == "titleOfClass":
                record["class"] = text
            elif tag == "cusip":
                record["cusip"] = text
            elif tag == "value":
                # 13F values reported in actual dollars (post Jan 2023 amendment).
                try:
                    record["value"] = int(float(text))
                except ValueError:
                    pass
            elif tag == "sshPrnamt":
                try:
                    record["shares"] = int(float(text))
                except ValueError:
                    pass
            elif tag == "sshPrnamtType":
                record["share_type"] = text
            elif tag == "putCall":
                record["put_call"] = text
            elif tag == "investmentDiscretion":
                record["discretion"] = text
            elif tag == "otherManager":
                record["manager"] = text
        if record["cusip"]:
            rows.append(record)
    return rows


# ---- Aggregation ---------------------------------------------------------

def consolidate(rows: list[dict]) -> dict[str, dict]:
    """Collapse multiple rows for the same CUSIP+class+put/call (Berkshire splits by manager).

    Keyed by (cusip, class, put_call). Values are summed; one issuer name is kept.
    """
    bucket: dict[tuple, dict] = {}
    for r in rows:
        key = (r["cusip"], r.get("class") or "", r.get("put_call") or "")
        if key not in bucket:
            bucket[key] = {
                "issuer": r["issuer"],
                "cusip": r["cusip"],
                "class": r["class"],
                "put_call": r["put_call"],
                "value": 0,
                "shares": 0,
                "share_type": r["share_type"],
            }
        bucket[key]["value"] += r["value"]
        bucket[key]["shares"] += r["shares"]
    return {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in bucket.items()}


def compute_changes(current: dict, prior: dict | None, prior2: dict | None) -> list[dict]:
    """For each holding in `current`, attach prior-quarter share/value deltas."""
    out = []
    for k, c in current.items():
        p = (prior or {}).get(k)
        p2 = (prior2 or {}).get(k)
        prev_shares = p["shares"] if p else 0
        prev_value = p["value"] if p else 0
        prev2_shares = p2["shares"] if p2 else 0
        delta_shares = c["shares"] - prev_shares
        if not p:
            status = "NEW"
        elif c["shares"] == 0:
            status = "SOLD"
        elif delta_shares > 0:
            status = "ADD"
        elif delta_shares < 0:
            status = "TRIM"
        else:
            status = "HOLD"
        out.append({
            **c,
            "prev_shares": prev_shares,
            "prev_value": prev_value,
            "prev2_shares": prev2_shares,
            "delta_shares": delta_shares,
            "delta_shares_pct": (delta_shares / prev_shares * 100.0) if prev_shares else None,
            "status": status,
        })
    # Also include positions present in prior but missing now (fully sold).
    for k, p in (prior or {}).items():
        if k in current:
            continue
        out.append({
            **p,
            "value": 0,
            "shares": 0,
            "prev_shares": p["shares"],
            "prev_value": p["value"],
            "prev2_shares": (prior2 or {}).get(k, {}).get("shares", 0),
            "delta_shares": -p["shares"],
            "delta_shares_pct": -100.0,
            "status": "SOLD",
        })
    return out


# ---- Driver --------------------------------------------------------------

def run() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "filers": []}

    for f in FILERS:
        print(f"== {f['name']} (CIK {f['cik']}) ==")
        quarters = []
        for acc in f["accessions"]:
            print(f"  fetching {acc} ...")
            filing = fetch_filing(f["cik"], acc)
            meta = parse_primary(filing["primary_xml"])
            rows = parse_infotable(filing["info_xml"])
            holdings = consolidate(rows)
            total_value = sum(h["value"] for h in holdings.values())
            quarters.append({
                "accession": acc,
                "period": meta.get("period"),
                "filer_name": meta.get("filer_name"),
                "holdings_count": meta.get("holdings_count"),
                "table_value_total": meta.get("table_value_total"),
                "computed_total_value": total_value,
                "holdings": holdings,
            })
            time.sleep(0.15)  # polite to EDGAR

        current_with_changes = compute_changes(
            quarters[0]["holdings"],
            quarters[1]["holdings"] if len(quarters) > 1 else None,
            quarters[2]["holdings"] if len(quarters) > 2 else None,
        )
        prior_with_changes = compute_changes(
            quarters[1]["holdings"] if len(quarters) > 1 else {},
            quarters[2]["holdings"] if len(quarters) > 2 else None,
            None,
        ) if len(quarters) > 1 else []

        out["filers"].append({
            "key": f["key"],
            "name": f["name"],
            "fund": f["fund"],
            "cik": f["cik"],
            "color": f["color"],
            "quarters": [
                {
                    "label": _quarter_label(quarters[i]["period"]),
                    "period": quarters[i]["period"],
                    "accession": quarters[i]["accession"],
                    "holdings_count": quarters[i]["holdings_count"],
                    "total_value": quarters[i]["computed_total_value"],
                }
                for i in range(len(quarters))
            ],
            "current_holdings": current_with_changes,
            "prior_holdings": prior_with_changes,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    # Also emit a JS file that sets a global, so the dashboard works from file://
    # (no server / CORS) as well as from http://.
    OUT_JS.write_text("window.HOLDINGS_DATA = " + json.dumps(out, separators=(",", ":")) + ";")
    print(f"\nwrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"wrote {OUT_JS} ({OUT_JS.stat().st_size:,} bytes)")


def _quarter_label(period: str | None) -> str | None:
    if not period:
        return None
    # period format: MM-DD-YYYY
    m = re.match(r"(\d{2})-(\d{2})-(\d{4})", period)
    if not m:
        return period
    month, _day, year = m.groups()
    q = (int(month) - 1) // 3 + 1
    return f"Q{q} {year}"


if __name__ == "__main__":
    run()
