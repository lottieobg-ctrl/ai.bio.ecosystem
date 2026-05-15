import json
import re
import time
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "events.json"
R2J = "https://api.rss2json.com/v1/api.json?rss_url="

# Search queries for discovering new AI × bio events
EVENT_QUERIES = [
    "AI biology conference 2026 registration",
    "biotech summit conference 2026",
    "synthetic biology conference 2026",
    "computational biology symposium 2026",
    "drug discovery AI conference 2026",
    "genomics bioinformatics conference 2026",
    "AI drug discovery summit 2026",
]

MONTHS = {
    'january':'01','february':'02','march':'03','april':'04',
    'may':'05','june':'06','july':'07','august':'08',
    'september':'09','october':'10','november':'11','december':'12',
}

DATE_PATTERNS = [
    re.compile(r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:[–\-]\d{1,2})?,?\s+(20\d{2})\b', re.IGNORECASE),
    re.compile(r'\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b', re.IGNORECASE),
]

EVENT_KW   = re.compile(r'\bconference\b|\bsummit\b|\bsymposium\b|\bcongress\b|\bworkshop\b|\bwebinar\b|\bhackathon\b|\bexpo\b', re.IGNORECASE)
BIO_AI_KW  = re.compile(r'bio(?:tech|logy|informatics|pharma)|\bAI\b|artificial intelligence|machine learning|genomic|synthetic biology|drug discovery|computational biology|proteomics|bioinformatics', re.IGNORECASE)


def load_events():
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return []


def save_events(events):
    with open(DATA_PATH, 'w') as f:
        json.dump(events, f, indent=2)


def prune_past(events):
    today = date.today().isoformat()
    kept = [e for e in events if (e.get('end_date') or e['date']) >= today]
    removed = len(events) - len(kept)
    if removed:
        print(f"Pruned {removed} past event(s)")
    return kept


def extract_date(text):
    for p in DATE_PATTERNS:
        m = p.search(text.lower())
        if m:
            try:
                g = m.groups()
                if g[0].isdigit():
                    day, month_name, year = g[0], g[1], g[2]
                else:
                    month_name, day, year = g[0], g[1], g[2]
                mm = MONTHS.get(month_name.lower())
                if mm:
                    return f"{year}-{mm}-{int(day):02d}"
            except Exception:
                pass
    return None


def fetch_rss(query):
    gn_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    api_url = R2J + urllib.parse.quote(gn_url, safe='')
    try:
        req = urllib.request.urlopen(api_url, timeout=12)
        data = json.loads(req.read().decode())
        return data.get('items', [])[:10]
    except Exception as e:
        print(f"RSS error ({query[:40]}): {e}")
        return []


def is_relevant(text):
    return bool(EVENT_KW.search(text)) and bool(BIO_AI_KW.search(text))


def main():
    today = date.today().isoformat()
    events = load_events()
    events = prune_past(events)

    existing_names = {e['name'].lower() for e in events}
    existing_urls  = {e['url'] for e in events if e.get('url')}
    added = []

    for query in EVENT_QUERIES:
        items = fetch_rss(query)
        for item in items:
            title   = item.get('title', '').strip()
            link    = item.get('link', '').strip()
            snippet = re.sub(r'<[^>]+>', '', item.get('description', '')).strip()
            text    = f"{title} {snippet}"

            if not is_relevant(text):
                continue

            ev_date = extract_date(text)
            if not ev_date or ev_date <= today:
                continue

            if title.lower() in existing_names or link in existing_urls:
                continue

            new_event = {
                "name": title[:140],
                "date": ev_date,
                "end_date": ev_date,
                "location": "TBC",
                "url": link,
                "type": "conference",
                "tags": ["AI", "biology"],
                "virtual": False,
                "description": snippet[:300] or title,
                "auto": True,
            }
            events.append(new_event)
            existing_names.add(title.lower())
            if link:
                existing_urls.add(link)
            added.append(title[:60])

        time.sleep(0.6)

    if added:
        print(f"Added {len(added)} auto-discovered event(s):")
        for name in added[:10]:
            print(f"  + {name}")

    events.sort(key=lambda e: e['date'])
    save_events(events)
    print(f"Total events: {len(events)}")


if __name__ == '__main__':
    main()
