#!/usr/bin/env python3
"""
Scrape Luma city pages for AI × Biology events.
Runs weekly via GitHub Actions and updates data/events.json.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests

CITIES = [
    {"name": "Boston, MA, USA",       "slug": "boston"},
    {"name": "San Francisco, CA, USA", "slug": "san-francisco"},
    {"name": "London, UK",             "slug": "london"},
    {"name": "Paris, France",          "slug": "paris"},
    {"name": "Berlin, Germany",        "slug": "berlin"},
]

AI_BIO_KEYWORDS = [
    "ai", "artificial intelligence", "machine learning",
    "biology", "biotech", "bioinformatics", "genomics",
    "drug discovery", "protein", "synthetic biology",
    "computational biology", "life science", "omics",
    "biopharma", "therapeutics", "pharma", "crispr",
    "gene editing", "cell therapy", "foundation model",
    "drug design", "molecular", "clinical ai", "bio+ai",
    "ai+bio", "ai x bio", "ai × bio", "ai bio",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AIxBioMap/1.0; +https://github.com/lottieobg-ctrl/ai.bio.ecosystem)",
    "Accept": "application/json, text/html, */*",
}


def is_ai_bio(name: str, desc: str = "") -> bool:
    text = (name + " " + desc).lower()
    return any(kw in text for kw in AI_BIO_KEYWORDS)


def fetch_city_events(city: dict) -> list:
    slug = city["slug"]

    # Attempt 1 — Luma internal discover API (no auth, public events only)
    try:
        r = requests.get(
            "https://api.lu.ma/discover/get-paginated-events",
            params={"filter": "city", "city_slugs": slug, "pagination_limit": 50},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            entries = data.get("entries") or data.get("events") or []
            if entries:
                print(f"  [{slug}] API returned {len(entries)} events", file=sys.stderr)
                return entries
    except Exception as e:
        print(f"  [{slug}] API error: {e}", file=sys.stderr)

    # Attempt 2 — parse __NEXT_DATA__ JSON embedded in the city page HTML
    try:
        r = requests.get(f"https://lu.ma/{slug}", headers=HEADERS, timeout=15)
        if r.status_code == 200:
            m = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                r.text, re.DOTALL,
            )
            if m:
                nd = json.loads(m.group(1))
                props = nd.get("props", {}).get("pageProps", {})
                events = (
                    props.get("events")
                    or props.get("initialEvents")
                    or props.get("featuredEvents")
                    or []
                )
                if events:
                    print(f"  [{slug}] HTML page returned {len(events)} events", file=sys.stderr)
                    return events
    except Exception as e:
        print(f"  [{slug}] HTML error: {e}", file=sys.stderr)

    print(f"  [{slug}] no events found", file=sys.stderr)
    return []


def parse_event(raw: dict, city: dict) -> dict | None:
    try:
        ev = raw.get("event") or raw  # sometimes nested under "event" key
        name = ev.get("name") or ev.get("title") or ""
        desc = ev.get("description") or ev.get("description_short") or ""
        if not name:
            return None
        if not is_ai_bio(name, desc):
            return None

        start = (ev.get("start_at") or ev.get("event_start_at") or "")[:10]
        end   = (ev.get("end_at")   or ev.get("event_end_at")   or start)[:10]
        if not start or end < date.today().isoformat():
            return None

        api_id = ev.get("api_id") or ev.get("id") or ""
        url = ev.get("url") or (f"https://lu.ma/{api_id}" if api_id else "")
        location = ev.get("location_name") or ev.get("location") or city["name"]
        virtual = bool(ev.get("is_virtual") or ev.get("virtual"))

        short_desc = desc.strip()
        if len(short_desc) > 300:
            short_desc = short_desc[:297] + "…"

        return {
            "name": name,
            "date": start,
            "end_date": end,
            "location": location,
            "url": url,
            "type": "meetup",
            "tags": ["AI", "biology"],
            "virtual": virtual,
            "description": short_desc,
            "source": "luma",
            "auto": True,
        }
    except Exception:
        return None


def main():
    repo_root = Path(__file__).resolve().parent.parent
    events_path = repo_root / "data" / "events.json"

    existing: list = json.loads(events_path.read_text()) if events_path.exists() else []
    today = date.today().isoformat()

    # Drop expired auto events; keep manual ones regardless of date
    kept = [e for e in existing if not e.get("auto") or (e.get("end_date") or e.get("date", "")) >= today]
    seen_urls = {e.get("url", "") for e in kept}

    added = 0
    for city in CITIES:
        print(f"Checking {city['name']}…", file=sys.stderr)
        for raw in fetch_city_events(city):
            parsed = parse_event(raw, city)
            if parsed and parsed["url"] and parsed["url"] not in seen_urls:
                kept.append(parsed)
                seen_urls.add(parsed["url"])
                added += 1
                print(f"  + {parsed['name']} ({parsed['date']})", file=sys.stderr)

    kept.sort(key=lambda e: e.get("date", ""))
    events_path.write_text(json.dumps(kept, indent=2, ensure_ascii=False))
    print(f"\nDone — {added} new events added, {len(kept)} total.", file=sys.stderr)


if __name__ == "__main__":
    main()
