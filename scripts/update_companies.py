import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

COMPANIES = [
    "EvolutionaryScale", "Chai Discovery", "Profluent", "BioMap", "Atomic AI", "NOETIK",
    "Inceptive", "Boltz Bio", "Latent Labs", "Goodfire", "Generate:Biomedicines", "Basecamp Research",
    "Absci", "Aignostics", "Atomwise", "BenevolentAI", "BigHat Biosciences",
    "Charm Therapeutics", "Chemify", "Cradle", "Deep Genomics", "Eikon Therapeutics", "Enveda",
    "Expression Edits", "Ginkgo Bioworks", "Healx", "Iktos", "Insilico Medicine", "insitro",
    "Isomorphic Labs", "Kailera Therapeutics", "Lila Biosciences", "Molecule.one", "1910 Genetics",
    "Olix", "Pathos AI", "Phylo Bio", "Qubit Pharmaceuticals", "Recursion Pharmaceuticals",
    "Relay Therapeutics", "Relation Therapeutics", "Schrodinger", "Superluminal Medicines",
    "Terray Therapeutics", "WhiteLab Genomics", "Xaira",
    "Automata", "Benchling", "Edison Scientific", "PacBio",
    "Gleamer", "Kaiko", "Medra", "Nabla", "Optellum", "Owkin", "Tempus AI",
    "Anthropic", "OpenAI", "Sakana AI",
    "Syncona",
]

DATA_PATH = Path(__file__).parent.parent / "data" / "companies.json"

FUNDING_KEYWORDS = re.compile(r'\braises?\b|\braised\b|\bfunding\b|\bseries [a-e]\b|\bseed\b|\bipo\b|\bacquir', re.IGNORECASE)
AMOUNT_PATTERN = re.compile(r'[\$£€](\d+(?:\.\d+)?)\s*(m|million|b|billion)\b', re.IGNORECASE)
STAGE_PATTERNS = [
    (re.compile(r'\bseries[- ]?c\b', re.IGNORECASE), 'series-c'),
    (re.compile(r'\bseries[- ]?b\b', re.IGNORECASE), 'series-b'),
    (re.compile(r'\bseries[- ]?a\b', re.IGNORECASE), 'series-a'),
    (re.compile(r'\bseed\b', re.IGNORECASE), 'seed'),
    (re.compile(r'\bipo\b|\bpublic\b|\blisted\b', re.IGNORECASE), 'public'),
    (re.compile(r'\bacquir', re.IGNORECASE), 'acquired'),
]


def load_data():
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return {"last_updated": None, "companies": []}


def save_data(data):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)


def fetch_rss(company):
    query = urllib.request.quote(f'"{company}" raises OR funding OR "Series"')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read()


def parse_amount(text):
    match = AMOUNT_PATTERN.search(text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower()
    if unit in ('b', 'billion'):
        return f"${number:.0f}B"
    return f"${number:.0f}M"


def parse_stage(text):
    for pattern, label in STAGE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def parse_pub_date(date_str):
    # RSS pubDate format: "Wed, 14 May 2026 08:00:00 GMT"
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def check_company(company, existing_entry):
    xml_data = fetch_rss(company)
    root = ET.fromstring(xml_data)
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_date_el = item.find("pubDate")

        if title_el is None or title_el.text is None:
            continue

        title = title_el.text
        link = link_el.text if link_el is not None else ""
        pub_date_str = pub_date_el.text if pub_date_el is not None else ""

        # Must mention the company name in the title
        if company.lower() not in title.lower():
            continue

        # Must be within the last 14 days
        pub_date = parse_pub_date(pub_date_str) if pub_date_str else None
        if pub_date and pub_date < cutoff:
            continue

        # Must look like a funding article
        if not FUNDING_KEYWORDS.search(title):
            continue

        # Skip if we already have this exact headline stored and it's not flagged for review
        if existing_entry and not existing_entry.get("needs_review"):
            stored_headline = existing_entry.get("review_headline", "")
            if stored_headline == title:
                return None

        # Don't overwrite an existing needs_review=True entry unless the headline has changed
        if existing_entry and existing_entry.get("needs_review"):
            stored_headline = existing_entry.get("review_headline", "")
            if stored_headline == title:
                return None

        amount = parse_amount(title)
        stage = parse_stage(title)

        return {
            "needs_review": True,
            "review_headline": title,
            "review_url": link,
            "proposed_funding": amount,
            "proposed_stage": stage,
            "found_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    return None


def main():
    data = load_data()
    companies_list = data.get("companies", [])

    # Build a dict keyed by name for easy lookup (preserves reference to list objects)
    company_map = {c['name']: c for c in companies_list}

    print(f"Checking {len(COMPANIES)} companies...")

    for company in COMPANIES:
        print(f"  Checking: {company}", end=" ", flush=True)

        # Skip companies not pre-populated in companies.json
        if company not in company_map:
            print("-> not in companies.json, skipping")
            continue

        existing = company_map[company]
        try:
            result = check_company(company, existing)
            if result:
                # Update the entry in-place (mutates the object in companies_list)
                existing["needs_review"] = True
                existing["review_headline"] = result["review_headline"]
                existing["review_url"] = result["review_url"]
                existing["found_at"] = result["found_at"]
                existing["proposed_funding"] = result["proposed_funding"] or ""
                existing["proposed_stage"] = result["proposed_stage"] or ""

                # Directly update funding and stage if both were parsed with high confidence
                if result["proposed_funding"] and result["proposed_stage"]:
                    existing["funding"] = result["proposed_funding"]
                    existing["stage"] = result["proposed_stage"]

                print(f"-> FLAGGED: {result['review_headline'][:60]}...")
            else:
                print("-> no new funding news")
        except Exception as e:
            print(f"-> ERROR: {e}")
        time.sleep(0.5)

    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["companies"] = companies_list
    save_data(data)
    print(f"\nDone. Data written to {DATA_PATH}")


if __name__ == "__main__":
    main()
