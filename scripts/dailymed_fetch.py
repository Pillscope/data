#!/usr/bin/env python3
"""
dailymed_fetch.py

Fetches every SPL (drug label) from DailyMed's REST API one at a time,
slims each to the fields a website needs, and writes it straight to disk.
Nothing raw is ever saved. Same pattern as mlb_historical_fetch.py:
fetch -> slim -> save, skip-existing, retries with backoff, coverage report.

Usage:
    python3 dailymed_fetch.py --limit 50                 # test run
    python3 dailymed_fetch.py --category rx               # full Rx run
    python3 dailymed_fetch.py --category otc               # full OTC run
    python3 dailymed_fetch.py --category rx --start-page 400   # resume
"""

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
REQUEST_DELAY = 0.6
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0
NS = {"hl7": "urn:hl7-org:v3"}

# LOINC codes for the sections we care about
SECTIONS_WANTED = {
    "34067-9": "indications_and_usage",
    "34068-7": "dosage_and_administration",
    "34070-3": "contraindications",
    "34071-1": "warnings",
    "34084-4": "adverse_reactions",
    "34073-7": "drug_interactions",
    "43685-7": "warnings_and_precautions",
    "34069-5": "boxed_warning",
}

DATA_DIR = Path("data")
FAILURES = 0
FAILED = object()


def fetch(url, as_json=True, retries=MAX_RETRIES):
    last_err = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "pillscope-ingest/1.0"})
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
            time.sleep(REQUEST_DELAY)
            if not raw:
                return None
            return json.loads(raw) if as_json else raw
        except HTTPError as e:
            if e.code == 404:
                return None
            last_err = e
        except (URLError, TimeoutError, json.JSONDecodeError, ET.ParseError) as e:
            last_err = e
        wait = RETRY_BACKOFF ** attempt
        print(f"    retry {attempt+1}/{retries} for {url} ({last_err}) - waiting {wait:.0f}s", file=sys.stderr)
        time.sleep(wait)
    print(f"    GAVE UP on {url}: {last_err}", file=sys.stderr)
    global FAILURES
    FAILURES += 1
    return FAILED


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def clean_text(elem):
    """Flatten an SPL <text> element into plain readable text."""
    text = "".join(elem.itertext())
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_spl_xml(raw_bytes, setid):
    root = ET.fromstring(raw_bytes)

    title_elem = root.find("hl7:title", NS)
    title = clean_text(title_elem) if title_elem is not None else ""

    sections = {}
    for section in root.iter("{urn:hl7-org:v3}section"):
        code_elem = section.find("hl7:code", NS)
        if code_elem is None:
            continue
        loinc = code_elem.get("code")
        if loinc not in SECTIONS_WANTED:
            continue
        text_elem = section.find("hl7:text", NS)
        if text_elem is not None:
            sections[SECTIONS_WANTED[loinc]] = clean_text(text_elem)

    active_ingredients = []
    for ingredient in root.iter("{urn:hl7-org:v3}ingredient"):
        if ingredient.get("classCode") != "ACTIB":
            continue
        name_elem = ingredient.find(".//hl7:ingredientSubstance/hl7:name", NS)
        if name_elem is not None and name_elem.text:
            active_ingredients.append(name_elem.text.strip())

    return {
        "setid": setid,
        "title": title,
        "active_ingredients": sorted(set(active_ingredients)),
        "sections": sections,
    }


def fetch_setid_list(category, page, pagesize=100):
    doctype = {
        "rx": "34391-3",
        "otc": "34390-5",
    }.get(category)
    url = f"{BASE}/spls.json?pagesize={pagesize}&page={page}"
    if doctype:
        url += f"&doctype={doctype}"
    return fetch(url, as_json=True)


def process_setid(setid, out_dir, skip_existing):
    path = out_dir / f"{setid}.json"
    if skip_existing and path.exists():
        return "skipped"
    raw = fetch(f"{BASE}/spls/{setid}.xml", as_json=False)
    if raw is FAILED:
        return "failed"
    if raw is None:
        return "empty"
    try:
        record = parse_spl_xml(raw, setid)
    except ET.ParseError as e:
        print(f"    parse error for {setid}: {e}", file=sys.stderr)
        return "failed"
    save_json(path, record)
    return "saved"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--category", choices=["rx", "otc", "all"], default="rx")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="Max number of labels to process (for testing)")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--output-dir", type=str, default="data/us")
    args = parser.parse_args()

    sys.stdout.reconfigure(line_buffering=True)

    global DATA_DIR
    DATA_DIR = Path(args.output_dir)
    out_dir = DATA_DIR / "spls"
    out_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    page = args.start_page
    counts = {"saved": 0, "skipped": 0, "failed": 0, "empty": 0}

    while True:
        listing = fetch_setid_list(args.category, page)
        if listing is FAILED or listing is None:
            print(f"Could not fetch page {page}, stopping.")
            break
        data = listing.get("data", [])
        if not data:
            print(f"No more results at page {page}. Done.")
            break

        total_pages = listing.get("metadata", {}).get("total_pages", "?")
        print(f"=== page {page}/{total_pages} ({len(data)} labels) ===")

        for item in data:
            setid = item.get("setid")
            if not setid:
                continue
            result = process_setid(setid, out_dir, args.skip_existing)
            counts[result] += 1
            processed += 1
            if processed % 50 == 0:
                print(f"  ...{processed} processed (saved={counts['saved']} skipped={counts['skipped']} failed={counts['failed']})")
            if args.limit and processed >= args.limit:
                print(f"Reached --limit {args.limit}, stopping.")
                print(counts)
                return

        page += 1

    print(f"\nFinal counts: {counts}")
    if FAILURES:
        print(f"{FAILURES} requests failed after retries. Rerun with the same --category to fill gaps (skip-existing will skip what's already saved).", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
