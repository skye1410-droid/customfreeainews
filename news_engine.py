"""
================================================================================
 NEWS ENGINE — shared core used by both the daily and weekly build scripts.
================================================================================
Zero third-party dependencies. Everything here is standard library:
urllib, xml.etree.ElementTree, re, html, datetime, socket.

Responsibilities:
  - Fetch + parse RSS feeds.
  - Custom RFC 2822 / ISO 8601 date parsing.
  - Deduplicate near-identical stories across feeds.
  - Cluster corroborating stories (same event, multiple outlets).
  - Score each story for "noteworthiness" (see module docstring in
    build_data.py for the full rationale).
  - Route each story into one of 8 "stacks".
================================================================================
"""

import re
import html
import socket
import datetime as dt
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

# ==============================================================================
# 1. STACKS (categories) + FEED CATALOGUE
# ==============================================================================

STACK_ORDER = [
    "Singapore",
    "United States",
    "Southeast Asia (SEA)",
    "World Affairs",
    "Geopolitics",
    "Healthcare & Biotech",
    "Technology & AI",
    "Business & Finance",
]

# Short badge codes shown next to each headline in the UI.
STACK_TAGS = {
    "Singapore": "SG",
    "United States": "US",
    "Southeast Asia (SEA)": "SEA",
    "World Affairs": "WORLD",
    "Geopolitics": "GEOPOLITICS",
    "Healthcare & Biotech": "HEALTH",
    "Technology & AI": "TECH",
    "Business & Finance": "FINANCE",
}

# Each stack maps to a list of (outlet_name, feed_url) tuples. Shown verbatim
# in the app's "Sources" tab, and used to fetch stories.
FEEDS = {
    "Singapore": [
        ("CNA — Singapore", "https://www.channelnewsasia.com/rssfeeds/8395986"),
        ("The Straits Times — Singapore", "https://www.straitstimes.com/news/singapore/rss.xml"),
        ("The Business Times — Singapore", "https://www.businesstimes.com.sg/rss/singapore"),
    ],
    "United States": [
        ("The New York Times — U.S.", "https://rss.nytimes.com/services/xml/rss/nyt/US.xml"),
        ("NPR — National", "https://feeds.npr.org/1003/rss.xml"),
        ("CNBC — Politics", "https://www.cnbc.com/id/15837362/device/rss/rss.html"),
    ],
    "Southeast Asia (SEA)": [
        ("CNA — Asia", "https://www.channelnewsasia.com/rssfeeds/8395984"),
        ("Bangkok Post — Top Stories", "https://www.bangkokpost.com/rss/data/topstories.xml"),
        ("Philstar — Headlines", "https://www.philstar.com/rss/headlines"),
    ],
    "World Affairs": [
        ("BBC — World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The New York Times — World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
        ("Fox News — World", "https://moxie.foxnews.com/google-publisher/world.xml"),
    ],
    "Geopolitics": [
        ("Foreign Policy", "https://foreignpolicy.com/feed/"),
        ("BBC — World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
        ("The New York Times — World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ],
    "Healthcare & Biotech": [
        ("STAT News", "https://www.statnews.com/feed/"),
        ("FDA — Press Releases", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"),
        ("The New York Times — Health", "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml"),
    ],
    "Technology & AI": [
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Wired", "https://www.wired.com/feed/rss"),
    ],
    "Business & Finance": [
        ("CNBC — Top News", "https://www.cnbc.com/id/10001147/device/rss/rss.html"),
        ("MarketWatch — Top Stories", "http://feeds.marketwatch.com/marketwatch/topstories/"),
        ("The New York Times — Business", "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ],
}

# --- Geographic keyword routing (checked before thematic routing) ----------
GEO_KEYWORDS = {
    "Singapore": [
        "singapore", "sgx", "changi", "temasek", "mas ", "monetary authority of singapore",
        "shangri-la dialogue", "hdb", "cpf", "grab holdings", "sg60",
    ],
    "United States": [
        "white house", "washington", "capitol hill", "senate", "congress",
        "wall street", "federal reserve", "the fed", "supreme court",
        "u.s. ", "us economy", "biden", "trump", "pentagon",
    ],
    "Southeast Asia (SEA)": [
        "malaysia", "indonesia", "vietnam", "thailand", "philippines",
        "asean", "jakarta", "kuala lumpur", "hanoi", "bangkok", "manila",
        "myanmar", "cambodia", "laos", "brunei",
    ],
}

THEMATIC_KEYWORDS = {
    "Geopolitics": [
        "diplomat", "sanctions", "ceasefire", "nato", "united nations",
        "security council", "military", "conflict", "border dispute",
        "foreign policy", "summit", "treaty", "geopolit",
    ],
    "Healthcare & Biotech": [
        "fda", "vaccine", "clinical trial", "biotech", "pharma", "hospital",
        "disease", "cancer", "drug approval", "cdc", "who ", "health",
    ],
    "Technology & AI": [
        "artificial intelligence", " ai ", "chatgpt", "semiconductor", "chip",
        "startup", "software", "cybersecurity", "app ", "silicon valley",
        "cloud computing", "data center", "robot",
    ],
    "Business & Finance": [
        "stock", "market", "earnings", "ipo", "merger", "acquisition",
        "central bank", "interest rate", "inflation", "gdp", "economy",
        "nasdaq", "dow jones", "s&p 500", "crypto", "bond",
    ],
    "World Affairs": [
        "breaking", "disaster", "earthquake", "election", "global",
        "crisis", "outbreak", "storm", "world",
    ],
}

GEO_STACKS = ["Singapore", "United States", "Southeast Asia (SEA)"]
THEMATIC_STACK_ORDER = [
    "Geopolitics", "Healthcare & Biotech", "Technology & AI",
    "Business & Finance", "World Affairs",
]

# ==============================================================================
# 2. NOTEWORTHINESS SCORING INPUTS
# ==============================================================================

# Editorial-authority tiers, keyed by source domain. Unlisted domains
# default to TIER_DEFAULT. This is a coarse, hand-maintained proxy for
# "how much editorial vetting did this likely get" — not a value judgment.
SOURCE_TIERS = {
    "reuters.com": 3, "bbc.co.uk": 3, "nytimes.com": 3, "wsj.com": 3,
    "bloomberg.com": 3, "apnews.com": 3,
    "cnbc.com": 2, "npr.org": 2, "straitstimes.com": 2,
    "channelnewsasia.com": 2, "businesstimes.com.sg": 2, "statnews.com": 2,
    "techcrunch.com": 2, "arstechnica.com": 2, "wired.com": 2,
    "marketwatch.com": 2, "foreignpolicy.com": 2, "bangkokpost.com": 2,
    "fda.gov": 2, "foxnews.com": 1, "philstar.com": 1,
}
TIER_DEFAULT = 1

SALIENCE_KEYWORDS = [
    "breaking", "urgent", "exclusive", "record", "historic", "unprecedented",
    "emergency", "crisis", "dies", "resigns", "resignation", "war", "attack",
    "surge", "surges", "plunge", "plunges", "crackdown", "landmark", "deal",
    "collapse", "election result", "wins", "sentenced", "indicted", "banned",
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "as", "is", "are", "was", "were", "be", "by", "at", "from",
    "that", "this", "it", "its", "their", "his", "her", "will", "has",
    "have", "had", "after", "over", "into", "amid", "says", "say", "said",
    "new", "than", "into", "about", "more", "how", "why", "what",
}

# Scoring weights — tune these to change ranking behaviour.
WEIGHT_CORROBORATION = 14   # per additional distinct source in the cluster
WEIGHT_TIER = 8             # per tier point (1-3)
WEIGHT_SALIENCE = 6         # per matched salience keyword
WEIGHT_POSITION = 10        # max bonus for being item #1 in its own feed, decaying
WEIGHT_RECENCY = 10         # max bonus for being freshest in the window


# ==============================================================================
# 3. DATE PARSING (RFC 2822 + ISO 8601, no dateutil)
# ==============================================================================

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_RFC2822_RE = re.compile(
    r"""
    (?:[A-Za-z]{3},\s*)?
    (?P<day>\d{1,2})\s+
    (?P<month>[A-Za-z]{3})[A-Za-z]*\s+
    (?P<year>\d{2,4})\s+
    (?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?
    \s*(?P<tz>[+-]\d{4}|[A-Za-z]{2,5})?
    """,
    re.VERBOSE,
)

_ISO8601_RE = re.compile(
    r"""
    (?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})
    [T\s]
    (?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})
    (?P<tz>Z|[+-]\d{2}:?\d{2})?
    """,
    re.VERBOSE,
)

_TZ_NAME_OFFSETS = {
    "UT": 0, "GMT": 0, "UTC": 0,
    "EST": -5 * 60, "EDT": -4 * 60,
    "CST": -6 * 60, "CDT": -5 * 60,
    "MST": -7 * 60, "MDT": -6 * 60,
    "PST": -8 * 60, "PDT": -7 * 60,
}


def _tz_offset_minutes(tz_token):
    if not tz_token:
        return 0
    tz_token = tz_token.strip().upper()
    if tz_token in _TZ_NAME_OFFSETS:
        return _TZ_NAME_OFFSETS[tz_token]
    match = re.match(r"^([+-])(\d{2}):?(\d{2})$", tz_token)
    if match:
        sign, hh, mm = match.groups()
        total = int(hh) * 60 + int(mm)
        return -total if sign == "-" else total
    return 0


def parse_pub_date(raw_date):
    """Parse RFC 2822 or ISO 8601 date strings into UTC-aware datetimes."""
    if not raw_date:
        return None
    raw_date = raw_date.strip()

    match = _RFC2822_RE.search(raw_date)
    if match:
        parts = match.groupdict()
        month = _MONTHS.get(parts["month"][:3].lower())
        if not month:
            return None
        year = int(parts["year"])
        if year < 100:
            year += 2000 if year < 70 else 1900
        try:
            naive = dt.datetime(
                year=year, month=month, day=int(parts["day"]),
                hour=int(parts["hour"]), minute=int(parts["minute"]),
                second=int(parts["second"] or 0),
            )
        except ValueError:
            return None
        offset = _tz_offset_minutes(parts.get("tz"))
        return (naive - dt.timedelta(minutes=offset)).replace(tzinfo=dt.timezone.utc)

    match = _ISO8601_RE.search(raw_date)
    if match:
        parts = match.groupdict()
        try:
            naive = dt.datetime(
                year=int(parts["year"]), month=int(parts["month"]), day=int(parts["day"]),
                hour=int(parts["hour"]), minute=int(parts["minute"]), second=int(parts["second"]),
            )
        except ValueError:
            return None
        offset = 0 if parts.get("tz") == "Z" else _tz_offset_minutes(parts.get("tz"))
        return (naive - dt.timedelta(minutes=offset)).replace(tzinfo=dt.timezone.utc)

    return None


# ==============================================================================
# 4. FETCHING & PARSING
# ==============================================================================

_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_WORD_RE = re.compile(r"[a-z0-9]+")

USER_AGENT = (
    "Mozilla/5.0 (compatible; NoteworthyNewsApp/1.0; "
    "+https://github.com/) Python-urllib"
)


def strip_html(raw_text):
    if not raw_text:
        return ""
    unescaped = html.unescape(raw_text)
    return _WHITESPACE_RE.sub(" ", _TAG_STRIP_RE.sub(" ", unescaped)).strip()


def truncate(text, max_chars=220):
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut.rstrip(",.;: ") + "..."


def normalize_title(title):
    return _NORMALIZE_RE.sub("", title.lower())


def significant_words(title):
    """Lowercased, stopword-free word set used for corroboration clustering."""
    words = _WORD_RE.findall(title.lower())
    return {w for w in words if w not in STOPWORDS and len(w) >= 4}


def domain_from_link(link):
    match = re.search(r"https?://(?:www\.)?([^/]+)", link or "")
    return match.group(1) if match else "unknown-source"


def fetch_feed_xml(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw_bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw_bytes.decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout,
            ConnectionError, TimeoutError, ValueError) as exc:
        print(f"[WARN] Failed to fetch feed '{url}': {exc}")
        return None


def parse_feed_items(xml_text, stack, outlet_name):
    """Parse RSS 2.0 / Atom XML into a list of story dicts."""
    items = []
    if not xml_text:
        return items
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"[WARN] XML parse error for '{outlet_name}' ({stack}): {exc}")
        return items

    entries = root.findall(".//item")
    is_atom = False
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        is_atom = True

    for position, entry in enumerate(entries):
        try:
            if is_atom:
                title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link_el = entry.find("{http://www.w3.org/2005/Atom}link")
                link = link_el.get("href") if link_el is not None else ""
                summary = (entry.findtext("{http://www.w3.org/2005/Atom}summary")
                           or entry.findtext("{http://www.w3.org/2005/Atom}content") or "")
                raw_date = (entry.findtext("{http://www.w3.org/2005/Atom}updated")
                            or entry.findtext("{http://www.w3.org/2005/Atom}published") or "")
            else:
                title = (entry.findtext("title") or "").strip()
                link = (entry.findtext("link") or "").strip()
                summary = (entry.findtext("description")
                           or entry.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
                raw_date = (entry.findtext("pubDate")
                            or entry.findtext("{http://purl.org/dc/elements/1.1/}date") or "")

            if not title or not link:
                continue

            items.append({
                "title": strip_html(title),
                "link": link.strip(),
                "snippet": truncate(strip_html(summary)),
                "published_utc": parse_pub_date(raw_date),
                "source_domain": domain_from_link(link),
                "outlet_name": outlet_name,
                "home_stack": stack,
                "feed_position": position,
            })
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Skipping malformed item from '{outlet_name}': {exc}")
            continue

    return items


def collect_all_articles():
    """Fetch every configured feed; return a flat list of parsed articles."""
    all_articles = []
    for stack, outlets in FEEDS.items():
        for outlet_name, url in outlets:
            xml_text = fetch_feed_xml(url)
            parsed = parse_feed_items(xml_text, stack, outlet_name)
            print(f"[INFO] {outlet_name}: {len(parsed)} items")
            all_articles.extend(parsed)
    return all_articles


# ==============================================================================
# 5. PIPELINE: TIME FILTER -> DEDUPE -> CLUSTER -> ROUTE -> SCORE
# ==============================================================================

def filter_recent(articles, now_utc, max_age_hours):
    cutoff = now_utc - dt.timedelta(hours=max_age_hours)
    return [a for a in articles
            if a["published_utc"] is not None and a["published_utc"] >= cutoff]


def deduplicate(articles):
    """Drop exact-duplicate titles (same story syndicated verbatim)."""
    seen, unique = set(), []
    for article in articles:
        key = normalize_title(article["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def cluster_corroborating_stories(articles, similarity_threshold=0.5):
    """
    Greedily group articles that appear to cover the same underlying event,
    based on Jaccard similarity of significant (stopword-free) title words.
    Mutates each article dict in place, adding:
        cluster_corroborators: list of {outlet_name, source_domain}
        corroboration_count: number of DISTINCT source domains in the cluster
    """
    clusters = []  # list of {"word_sets": [...], "members": [article, ...]}

    for article in articles:
        words = significant_words(article["title"])
        placed = False
        for cluster in clusters:
            for existing_words in cluster["word_sets"]:
                if not words or not existing_words:
                    continue
                overlap = len(words & existing_words) / len(words | existing_words)
                if overlap >= similarity_threshold:
                    cluster["word_sets"].append(words)
                    cluster["members"].append(article)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            clusters.append({"word_sets": [words], "members": [article]})

    for cluster in clusters:
        distinct_domains = {m["source_domain"] for m in cluster["members"]}
        corroborators = [
            {"outlet_name": m["outlet_name"], "source_domain": m["source_domain"]}
            for m in cluster["members"]
        ]
        for member in cluster["members"]:
            member["corroboration_count"] = len(distinct_domains)
            member["cluster_corroborators"] = corroborators

    return articles


def matches_any_keyword(text, keywords):
    lowered = f" {text.lower()} "
    return any(keyword in lowered for keyword in keywords)


def route_article(article):
    """Geographic keywords first, then thematic, then home-feed fallback."""
    haystack = f"{article['title']} {article['snippet']}"
    for stack in GEO_STACKS:
        if matches_any_keyword(haystack, GEO_KEYWORDS[stack]):
            return stack
    for stack in THEMATIC_STACK_ORDER:
        if matches_any_keyword(haystack, THEMATIC_KEYWORDS.get(stack, [])):
            return stack
    return article["home_stack"] if article["home_stack"] in STACK_ORDER else None


def score_article(article, now_utc, window_hours):
    """
    Composite 0-100ish "noteworthiness" score. See build_data.py's module
    docstring for the rationale behind each component.
    """
    tier = SOURCE_TIERS.get(article["source_domain"], TIER_DEFAULT)
    tier_score = tier * WEIGHT_TIER

    corroboration_score = (article.get("corroboration_count", 1) - 1) * WEIGHT_CORROBORATION

    salience_hits = sum(1 for kw in SALIENCE_KEYWORDS if kw in article["title"].lower())
    salience_score = salience_hits * WEIGHT_SALIENCE

    # Position: item 0 in its feed gets full bonus, decaying to ~0 by item 10.
    position_score = WEIGHT_POSITION * max(0.0, 1 - article["feed_position"] / 10)

    # Recency: freshest article in the window gets full bonus, decaying linearly.
    if article["published_utc"] is not None:
        age_hours = (now_utc - article["published_utc"]).total_seconds() / 3600
        recency_score = WEIGHT_RECENCY * max(0.0, 1 - age_hours / window_hours)
    else:
        recency_score = 0.0

    total = tier_score + corroboration_score + salience_score + position_score + recency_score
    return round(total, 1)


def build_dataset(now_utc, window_hours, max_per_stack, min_score):
    """
    Run the full pipeline and return a dict keyed by stack name, each value
    a list of scored, sorted story dicts (highest noteworthiness first),
    capped at max_per_stack and filtered to score >= min_score.
    """
    raw = collect_all_articles()
    print(f"[INFO] Collected {len(raw)} raw articles")

    recent = filter_recent(raw, now_utc, window_hours)
    print(f"[INFO] {len(recent)} articles within the last {window_hours}h window")

    unique = deduplicate(recent)
    print(f"[INFO] {len(unique)} unique articles after dedup")

    clustered = cluster_corroborating_stories(unique)

    for article in clustered:
        article["stack"] = route_article(article)
        article["score"] = score_article(article, now_utc, window_hours)

    routed = [a for a in clustered if a["stack"] in STACK_ORDER]

    dataset = {}
    for stack in STACK_ORDER:
        candidates = [a for a in routed if a["stack"] == stack]
        candidates.sort(key=lambda a: a["score"], reverse=True)
        qualifying = [a for a in candidates if a["score"] >= min_score][:max_per_stack]
        dataset[stack] = qualifying
        print(f"[INFO] {stack}: {len(qualifying)}/{max_per_stack} stories "
              f"(from {len(candidates)} candidates)")

    return dataset
