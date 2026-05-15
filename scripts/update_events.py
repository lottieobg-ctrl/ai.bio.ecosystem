import json
import re
import time
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

DATA_PATH = Path(__file__).parent.parent / "data" / "events.json"
R2J = "https://api.rss2json.com/v1/api.json?rss_url="

UA = 'Mozilla/5.0 (compatible; AIxBioMapBot/1.0; events aggregator)'

# Google News RSS — broader and conference-focused queries
EVENT_QUERIES = [
    "AI biology conference 2026 registration",
    "biotech summit conference 2026",
    "synthetic biology conference 2026",
    "computational biology symposium 2026",
    "drug discovery AI conference 2026",
    "genomics bioinformatics conference 2026",
    "AI drug discovery summit 2026",
    # Targeted: specific organisations and platforms
    "VentureCafe AI biotech event 2026",
    "ARIA advanced research event science 2026",
    "SOTA society technological advancement AI event",
    "luma lu.ma AI biology meetup 2026",
]

# Luma discover search terms — niche community events
LUMA_QUERIES = [
    "AI biology",
    "biotech AI",
    "synthetic biology",
    "drug discovery AI",
    "computational biology",
    "AI genomics",
    "AI for science",
    "bio AI",
]

# Slugs/paths that are Luma site navigation, not events
LUMA_SKIP = {
    'discover', 'about', 'pricing', 'login', 'signup', 'terms',
    'privacy', 'help', 'calendar', 'home', 'contact', 'blog',
    'press', 'api', 'legal', 'faq', 'features', 'community',
    'explore', 'create', 'settings', 'notifications', 'search',
}

MONTHS = {
    'january':'01','february':'02','march':'03','april':'04',
    'may':'05','june':'06','july':'07','august':'08',
    'september':'09','october':'10','november':'11','december':'12',
}

DATE_PATTERNS = [
    re.compile(r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(?:[–\-]\d{1,2})?,?\s+(20\d{2})\b', re.IGNORECASE),
    re.compile(r'\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b', re.IGNORECASE),
]

EVENT_KW  = re.compile(r'\bconference\b|\bsummit\b|\bsymposium\b|\bcongress\b|\bworkshop\b|\bwebinar\b|\bhackathon\b|\bexpo\b|\bmeetup\b|\bgathering\b|\bseminar\b', re.IGNORECASE)
BIO_AI_KW = re.compile(r'bio(?:tech|logy|informatics|pharma)|\bAI\b|artificial intelligence|machine learning|genomic|synthetic biology|drug discovery|computational biology|proteomics|bioinformatics|foundation model|protein|CRISPR|omics|life science', re.IGNORECASE)


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


def iso_to_date(s):
    """Extract YYYY-MM-DD from an ISO datetime string."""
    if not s:
        return None
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s)
    return m.group(1) if m else None


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


def is_bio_ai(text):
    """Looser check — biology/AI relevance only, no event-type keyword required."""
    return bool(BIO_AI_KW.search(text))


def fetch_url(url, timeout=12):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp.read().decode('utf-8', errors='ignore')


def fetch_luma_event_page(url):
    """Parse a Luma event page and return a structured event dict or None."""
    try:
        html = fetch_url(url)

        # Try JSON-LD structured data (Luma emits Event schema)
        for jld_m in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(jld_m.group(1))
                if isinstance(data, list):
                    data = next((d for d in data if d.get('@type') == 'Event'), data[0] if data else {})
                if data.get('@type') != 'Event':
                    continue

                name = data.get('name', '').strip()
                start = iso_to_date(data.get('startDate', ''))
                end   = iso_to_date(data.get('endDate', '')) or start

                loc_data = data.get('location', {})
                if isinstance(loc_data, dict):
                    loc = (loc_data.get('name') or
                           loc_data.get('address', {}).get('addressLocality') or 'TBC')
                elif isinstance(loc_data, list) and loc_data:
                    loc = loc_data[0].get('name', 'TBC')
                else:
                    loc = 'TBC'

                desc = re.sub(r'<[^>]+>', ' ', data.get('description', '')).strip()[:300]
                virtual = 'Online' in (data.get('eventAttendanceMode', '') or '') or loc.lower() in ('online', 'virtual')

                if name and start and is_bio_ai(f"{name} {desc}"):
                    return {
                        "name": name[:140],
                        "date": start,
                        "end_date": end,
                        "location": loc,
                        "url": url,
                        "type": "meetup",
                        "tags": ["AI", "biology"],
                        "virtual": virtual,
                        "description": desc or name,
                        "auto": True,
                    }
            except Exception:
                pass

        # Fallback: og:title + date regex
        title_m = re.search(r'<meta\s+(?:property=["\']og:title["\']|name=["\']title["\'])[^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not title_m:
            title_m = re.search(r'<title[^>]*>([^<|]+)', html, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else None

        if title and is_bio_ai(title):
            ev_date = extract_date(html)
            if ev_date:
                return {
                    "name": title[:140],
                    "date": ev_date,
                    "end_date": ev_date,
                    "location": "TBC",
                    "url": url,
                    "type": "meetup",
                    "tags": ["AI", "biology"],
                    "virtual": False,
                    "description": title,
                    "auto": True,
                }
    except Exception as e:
        print(f"Luma event error ({url}): {e}")
    return None


def fetch_luma_events():
    """Scrape Luma discover pages and return AI×bio community events."""
    found_slugs = {}  # slug -> nearby context text

    for query in LUMA_QUERIES:
        url = f"https://luma.com/discover?q={urllib.parse.quote(query)}"
        try:
            html = fetch_url(url, timeout=15)
            # Extract event href slugs (typically 5-20 alphanumeric chars)
            for m in re.finditer(r'href="(/[a-z0-9][a-z0-9-]{4,19})"', html):
                slug = m.group(1).lstrip('/')
                if slug in LUMA_SKIP or '/' in slug:
                    continue
                if slug not in found_slugs:
                    # Grab surrounding text as rough title context
                    pos = m.start()
                    window = html[max(0, pos - 300):pos + 300]
                    context = re.sub(r'<[^>]+>', ' ', window)
                    context = re.sub(r'\s+', ' ', context).strip()
                    found_slugs[slug] = context
        except Exception as e:
            print(f"Luma discover error ({query}): {e}")
        time.sleep(0.8)

    print(f"Luma: {len(found_slugs)} unique slugs found, filtering for relevance…")

    events = []
    checked = 0
    for slug, context in found_slugs.items():
        if not is_bio_ai(context):
            continue
        ev_url = f"https://luma.com/{slug}"
        ev = fetch_luma_event_page(ev_url)
        if ev:
            events.append(ev)
        checked += 1
        if checked >= 25:  # cap to keep the action fast
            break
        time.sleep(0.5)

    print(f"Luma: checked {checked} relevant slugs, found {len(events)} events")
    return events


def main():
    today = date.today().isoformat()
    events = load_events()
    events = prune_past(events)

    existing_names = {e['name'].lower() for e in events}
    existing_urls  = {e['url'] for e in events if e.get('url')}
    added = []

    # — Google News RSS (conferences, summits, VentureCafe, ARIA, SOTA) —
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

    # — Luma community events —
    luma_events = fetch_luma_events()
    for ev in luma_events:
        if not ev.get('date') or ev['date'] <= today:
            continue
        if ev['name'].lower() in existing_names or ev.get('url') in existing_urls:
            continue
        events.append(ev)
        existing_names.add(ev['name'].lower())
        if ev.get('url'):
            existing_urls.add(ev['url'])
        added.append(f"[Luma] {ev['name'][:55]}")

    if added:
        print(f"Added {len(added)} auto-discovered event(s):")
        for name in added[:15]:
            print(f"  + {name}")

    events.sort(key=lambda e: e['date'])
    save_events(events)
    print(f"Total events: {len(events)}")


if __name__ == '__main__':
    main()
