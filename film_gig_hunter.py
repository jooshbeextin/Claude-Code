#!/usr/bin/env python3
"""
Film Gig Hunter — Personal edition (wrangler + producer)
Scrapes Staff Me Up, Mandy.com, Craigslist, and Indeed for NYC + Toronto
film industry gigs, scores with Claude, delivers via Telegram.
"""

import os
import json
import re
import sys
import time
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

CACHE_FILE     = Path("gig_cache.json")
CACHE_TTL_DAYS = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def hr(char="─", width=62):
    return char * width


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"seen": {}}


def save_cache(cache: dict):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def prune_cache(cache: dict) -> dict:
    cutoff = (datetime.now() - timedelta(days=CACHE_TTL_DAYS)).isoformat()
    cache["seen"] = {k: v for k, v in cache.get("seen", {}).items() if v >= cutoff}
    return cache


def gig_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


def clean_text(text: str, max_len: int = 500) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;",  "&",  text)
    text = re.sub(r"&lt;",   "<",  text)
    text = re.sub(r"&gt;",   ">",  text)
    text = re.sub(r"&quot;", '"',  text)
    text = re.sub(r"&#?\w+;", "",  text)
    text = " ".join(text.split())
    return text[:max_len]


def make_gig(title: str, url: str, desc: str, source: str, market: str,
             published: str = "") -> dict:
    return {
        "title":       title.strip(),
        "url":         url.strip(),
        "description": clean_text(desc),
        "published":   published,
        "source":      source,
        "market":      market,
    }


# ─────────────────────────────────────────────────────────────
# RSS fetcher (Indeed + Craigslist)
# ─────────────────────────────────────────────────────────────

def fetch_rss(url: str, source_name: str, market: str) -> list[dict]:
    gigs = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
        root    = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = item.findtext("description", "")
            pub   = item.findtext("pubDate", "").strip()
            if title and link:
                gigs.append(make_gig(title, link, desc, source_name, market, pub))
    except Exception as e:
        print(f"  ⚠  RSS [{source_name}]: {e}")
    return gigs


def fetch_indeed(markets: list[str]) -> list[dict]:
    """Indeed RSS — catches corporate/staff postings."""
    feeds = []
    if "NYC" in markets:
        base = "https://www.indeed.com/rss?sort=date&fromage=3&l=New+York+City%2C+NY&q="
        feeds += [
            (base + "wrangler+film",                  "Indeed NYC",     "NYC"),
            (base + "producer+film+freelance",         "Indeed NYC",     "NYC"),
            (base + "line+producer",                   "Indeed NYC",     "NYC"),
            (base + "production+coordinator+film",     "Indeed NYC",     "NYC"),
            (base + "%22branded+content%22+producer",  "Indeed NYC",     "NYC"),
        ]
    if "Toronto" in markets:
        base = "https://ca.indeed.com/rss?sort=date&fromage=3&l=Toronto%2C+Ontario&q="
        feeds += [
            (base + "wrangler+film",                  "Indeed Toronto", "Toronto"),
            (base + "producer+film+freelance",         "Indeed Toronto", "Toronto"),
            (base + "line+producer",                   "Indeed Toronto", "Toronto"),
            (base + "production+coordinator+film",     "Indeed Toronto", "Toronto"),
        ]

    gigs = []
    for url, name, market in feeds:
        gigs += fetch_rss(url, name, market)
        time.sleep(0.6)
    return gigs


def fetch_craigslist(markets: list[str]) -> list[dict]:
    """Craigslist TV/Film jobs + creative gigs — high signal for freelance crew."""
    feeds = []
    if "NYC" in markets:
        feeds += [
            ("https://newyork.craigslist.org/search/tfr?format=rss", "Craigslist NYC Jobs", "NYC"),
            ("https://newyork.craigslist.org/search/crg?format=rss", "Craigslist NYC Gigs", "NYC"),
        ]
    if "Toronto" in markets:
        feeds += [
            ("https://toronto.craigslist.org/search/tfr?format=rss",  "Craigslist Toronto Jobs", "Toronto"),
            ("https://toronto.craigslist.org/search/crg?format=rss",  "Craigslist Toronto Gigs", "Toronto"),
        ]

    gigs = []
    for url, name, market in feeds:
        gigs += fetch_rss(url, name, market)
        time.sleep(0.5)
    return gigs


# ─────────────────────────────────────────────────────────────
# Staff Me Up scraper
# ─────────────────────────────────────────────────────────────

def scrape_staffmeup(markets: list[str]) -> list[dict]:
    """
    Staff Me Up — the primary North American film/TV job board.
    Searches for wrangler, producer, and production coordinator roles.
    """
    role_queries = ["wrangler", "producer", "line producer", "production coordinator"]
    location_map = {
        "NYC":     "New York",
        "Toronto": "Toronto",
    }
    gigs = []

    for market in markets:
        location = location_map.get(market, market)
        for role in role_queries:
            url = (
                "https://www.staffmeup.com/jobs?"
                + urllib.parse.urlencode({"q": role, "location": location})
            )
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                # Staff Me Up job cards — try multiple selector patterns
                cards = (
                    soup.select(".job-card")
                    or soup.select("[class*='job-card']")
                    or soup.select("[class*='JobCard']")
                    or soup.select("article")
                )

                for card in cards:
                    a_tag = card.find("a", href=True)
                    if not a_tag:
                        continue
                    title_el = (
                        card.find(["h2", "h3", "h4"])
                        or card.find(class_=re.compile(r"title", re.I))
                    )
                    desc_el  = card.find("p") or card.find(class_=re.compile(r"desc|summary", re.I))

                    title = (title_el.get_text(strip=True) if title_el
                             else a_tag.get_text(strip=True))
                    if not title:
                        continue

                    href = a_tag["href"]
                    if not href.startswith("http"):
                        href = "https://www.staffmeup.com" + href

                    desc = desc_el.get_text(strip=True) if desc_el else ""
                    gigs.append(make_gig(title, href, desc, f"Staff Me Up {market}", market))

                time.sleep(1.5)
            except Exception as e:
                print(f"  ⚠  Staff Me Up {market} [{role}]: {e}")

    return gigs


# ─────────────────────────────────────────────────────────────
# Mandy.com scraper
# ─────────────────────────────────────────────────────────────

def scrape_mandy(markets: list[str]) -> list[dict]:
    """
    Mandy.com — major international film crew marketplace.
    Covers both job listings and crew calls.
    """
    url_map = {
        "NYC":     "https://www.mandy.com/us/film-jobs/",
        "Toronto": "https://www.mandy.com/ca/film-jobs/",
    }
    gigs = []

    for market in markets:
        url = url_map.get(market)
        if not url:
            continue
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Mandy listing items — try common patterns
            items = (
                soup.select(".job-listing")
                or soup.select("[class*='listing']")
                or soup.select("[class*='job-item']")
                or soup.select("li.result")
                or soup.select(".result-item")
            )

            for item in items:
                a_tag = item.find("a", href=True)
                if not a_tag:
                    continue
                title_el = (
                    item.find(["h2", "h3", "h4"])
                    or item.find(class_=re.compile(r"title|heading", re.I))
                )
                desc_el  = item.find("p") or item.find(class_=re.compile(r"desc|summary|snippet", re.I))

                title = (title_el.get_text(strip=True) if title_el
                         else a_tag.get_text(strip=True))
                if not title:
                    continue

                href = a_tag["href"]
                if not href.startswith("http"):
                    href = "https://www.mandy.com" + href

                desc = desc_el.get_text(strip=True) if desc_el else ""
                gigs.append(make_gig(title, href, desc, f"Mandy.com {market}", market))

            time.sleep(1.2)
        except Exception as e:
            print(f"  ⚠  Mandy.com {market}: {e}")

    return gigs


# ─────────────────────────────────────────────────────────────
# ProductionHub scraper
# ─────────────────────────────────────────────────────────────

def scrape_productionhub(markets: list[str]) -> list[dict]:
    """ProductionHub — production industry job board with wrangler/producer listings."""
    gigs = []
    role_terms = ["wrangler", "producer", "production+coordinator"]

    for market in markets:
        loc = "new-york" if market == "NYC" else "toronto"
        for term in role_terms:
            url = f"https://www.productionhub.com/jobs?q={term}&location={loc}"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                items = (
                    soup.select(".job-listing")
                    or soup.select("[class*='job-listing']")
                    or soup.select(".listing-item")
                    or soup.select("[class*='JobListing']")
                )

                for item in items:
                    a_tag = item.find("a", href=True)
                    if not a_tag:
                        continue
                    title_el = item.find(["h2", "h3", "h4"]) or a_tag
                    desc_el  = item.find("p")

                    title = title_el.get_text(strip=True)
                    if not title:
                        continue

                    href = a_tag["href"]
                    if not href.startswith("http"):
                        href = "https://www.productionhub.com" + href

                    desc = desc_el.get_text(strip=True) if desc_el else ""
                    gigs.append(make_gig(title, href, desc, f"ProductionHub {market}", market))

                time.sleep(1.2)
            except Exception as e:
                print(f"  ⚠  ProductionHub {market} [{term}]: {e}")

    return gigs


# ─────────────────────────────────────────────────────────────
# Aggregate all sources
# ─────────────────────────────────────────────────────────────

def fetch_all_gigs(config: dict) -> list[dict]:
    gig_cfg = config.get("film_gigs", {})
    markets = gig_cfg.get("markets", ["NYC", "Toronto"])
    sources = gig_cfg.get("sources", ["craigslist", "staffmeup", "mandy", "productionhub", "indeed"])

    all_gigs:   list[dict]  = []
    seen_urls:  set[str]    = set()

    def add(fetched: list[dict]):
        for g in fetched:
            if g["url"] not in seen_urls:
                seen_urls.add(g["url"])
                all_gigs.append(g)

    if "craigslist"   in sources:
        print("  Fetching Craigslist (TV/Film jobs + creative gigs)...")
        add(fetch_craigslist(markets))

    if "staffmeup"    in sources:
        print("  Fetching Staff Me Up...")
        add(scrape_staffmeup(markets))

    if "mandy"        in sources:
        print("  Fetching Mandy.com...")
        add(scrape_mandy(markets))

    if "productionhub" in sources:
        print("  Fetching ProductionHub...")
        add(scrape_productionhub(markets))

    if "indeed"       in sources:
        print("  Fetching Indeed...")
        add(fetch_indeed(markets))

    # User-defined custom RSS sources
    for src in gig_cfg.get("custom_rss_sources", []):
        if src.get("market") in markets:
            print(f"  Fetching {src['name']}...")
            add(fetch_rss(src["url"], src["name"], src["market"]))
            time.sleep(0.5)

    return all_gigs


# ─────────────────────────────────────────────────────────────
# Claude scoring — personal profile (wrangler + producer)
# ─────────────────────────────────────────────────────────────

SCORE_SYSTEM = """You are reviewing film industry job listings on behalf of a freelance
wrangler and producer based between NYC and Toronto. Your job is to identify which postings
are genuinely worth applying to — direct fits, adjacent roles, and networking opportunities."""


def score_batch(client: anthropic.Anthropic, batch: list[dict], config: dict) -> list[dict]:
    profile   = config.get("film_gigs", {}).get("profile", {})
    name      = profile.get("name", "Josh")
    roles     = profile.get("roles", ["wrangler", "producer"])
    notes     = profile.get("notes", "")
    threshold = config.get("film_gigs", {}).get("min_score", 6)

    roles_str = " and ".join(roles)
    gig_list = "\n\n".join([
        f"GIG {i+1}:\nTitle: {g['title']}\nMarket: {g['market']}\n"
        f"Source: {g['source']}\nDescription: {g['description'][:450]}"
        for i, g in enumerate(batch)
    ])

    prompt = f"""Score each job listing for relevance to {name}, a freelance film industry professional.

{name}'s profile:
- Primary roles: {roles_str}
- Markets: NYC and Toronto
{('- Notes: ' + notes) if notes else ''}

Scoring guide (1–10):
10 = Direct role match — wrangler call, producer/line producer/production coordinator gig
8–9 = Strong adjacent fit — 1st/2nd AD, set coordinator, production manager, PA on a real production
6–7 = Possible fit — producing-adjacent, BTS producer, branded content shoot needing crew
4–5 = Stretch — staff production role, post-production, photography-adjacent
1–3 = Not relevant — retail, office, IT, unrelated industry

Wrangler context: could mean animal wrangler, talent/extras wrangler, or child wrangler.
Score any wrangler role high regardless of subtype.

{gig_list}

Respond ONLY with a valid JSON array — no markdown, no extra text:
[{{"gig":1,"score":8,"summary":"One sentence: what the gig is and why it fits"}},...]"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        system=SCORE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw   = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    results = json.loads(raw)
    scored  = []
    for r in results:
        idx = r.get("gig", 0) - 1
        if 0 <= idx < len(batch) and r.get("score", 0) >= threshold:
            gig            = batch[idx].copy()
            gig["score"]   = r["score"]
            gig["summary"] = r.get("summary", gig["title"])
            scored.append(gig)
    return scored


def score_all(gigs: list[dict], config: dict) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    client     = anthropic.Anthropic(api_key=api_key)
    all_scored = []
    batch_size = 5

    for i in range(0, len(gigs), batch_size):
        batch = gigs[i : i + batch_size]
        try:
            all_scored.extend(score_batch(client, batch, config))
        except Exception as e:
            print(f"  ⚠  Scoring batch {i // batch_size + 1} failed: {e}")
        time.sleep(0.3)

    return sorted(all_scored, key=lambda x: x["score"], reverse=True)


# ─────────────────────────────────────────────────────────────
# Telegram delivery
# ─────────────────────────────────────────────────────────────

def _tg_post(token: str, chat_id: str, text: str) -> None:
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Telegram returned HTTP {resp.status}")


def send_telegram(gigs: list[dict], markets: list[str]) -> bool:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    now    = datetime.now().strftime("%b %d · %H:%M")
    plural = "s" if len(gigs) != 1 else ""
    _tg_post(token, chat_id, (
        f"🎬 <b>FILM GIG ALERT</b>  ·  {now}\n"
        f"📍 {' + '.join(markets)}  ·  {len(gigs)} new gig{plural}\n"
        f"{'─' * 32}"
    ))

    for g in gigs:
        dot    = "🟢" if g["score"] >= 8 else "🟡"
        source = g["source"].split(" — ")[0]
        try:
            _tg_post(token, chat_id, (
                f"{dot} <b>{g['title']}</b>\n"
                f"📌 {g['market']}  ·  {source}  ·  {g['score']}/10\n"
                f"📝 {g['summary']}\n"
                f'🔗 <a href="{g["url"]}">View posting</a>'
            ))
        except Exception as e:
            print(f"  ⚠  Telegram: {e}")
        time.sleep(0.4)

    return True


# ─────────────────────────────────────────────────────────────
# Save digest
# ─────────────────────────────────────────────────────────────

def save_digest(gigs: list[dict]) -> str:
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    slug     = datetime.now().strftime("%Y-%m-%d-%H%M")
    filepath = reports_dir / f"gigs-{slug}.md"
    lines    = [
        f"# Film Gig Digest  ·  {datetime.now().strftime('%B %d, %Y  %H:%M')}\n\n",
        f"**{len(gigs)} relevant gig{'s' if len(gigs) != 1 else ''}**\n\n",
    ]
    for g in gigs:
        lines.append(f"## [{g['score']}/10]  {g['title']}\n\n")
        lines.append(f"- **Market:** {g['market']}\n")
        lines.append(f"- **Source:** {g['source']}\n")
        lines.append(f"- **Summary:** {g['summary']}\n")
        lines.append(f"- **URL:** {g['url']}\n")
        if g.get("published"):
            lines.append(f"- **Posted:** {g['published']}\n")
        lines.append("\n")
    with open(filepath, "w") as f:
        f.writelines(lines)
    return str(filepath)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    config     = load_config()
    gig_cfg    = config.get("film_gigs", {})
    markets    = gig_cfg.get("markets", ["NYC", "Toronto"])
    threshold  = gig_cfg.get("min_score", 6)
    max_alerts = gig_cfg.get("max_alerts_per_run", 20)
    profile    = gig_cfg.get("profile", {})
    name       = profile.get("name", "Josh")
    roles      = profile.get("roles", ["wrangler", "producer"])

    print("\n" + hr("═"))
    print(f"  FILM GIG HUNTER  ·  {datetime.now().strftime('%A, %B %d, %Y  %H:%M')}")
    print(f"  Profile: {name}  ·  {' + '.join(roles)}")
    print(f"  Markets: {', '.join(markets)}  ·  Min score: {threshold}/10")
    print(hr("═") + "\n")

    cache = prune_cache(load_cache())

    print(hr())
    print("  FETCHING LISTINGS")
    print(hr())
    all_gigs = fetch_all_gigs(config)
    print(f"\n  Total fetched:  {len(all_gigs)}")

    new_pairs: list[tuple[str, dict]] = [
        (gig_id(g["url"]), g)
        for g in all_gigs
        if gig_id(g["url"]) not in cache.get("seen", {})
    ]
    print(f"  New (unseen):   {len(new_pairs)}")

    if not new_pairs:
        print("\n  Nothing new since last run — all caught up.")
        save_cache(cache)
        print(f"\n{hr('═')}\n")
        return

    now_iso = datetime.now().isoformat()
    for gid, _ in new_pairs:
        cache.setdefault("seen", {})[gid] = now_iso
    save_cache(cache)

    gigs_to_score = [g for _, g in new_pairs]

    print(f"\n{hr()}")
    print("  SCORING WITH CLAUDE")
    print(hr())
    print(f"  Evaluating {len(gigs_to_score)} new listings...")
    scored = score_all(gigs_to_score, config)
    print(f"  Relevant (≥{threshold}/10): {len(scored)}")

    if not scored:
        print("\n  No high-relevance gigs found this run.")
        print(f"\n{hr('═')}\n")
        return

    top = scored[:max_alerts]

    print(f"\n{hr()}")
    print(f"  TOP GIGS  ({len(top)} shown)")
    print(hr())
    for g in top:
        dot = "🟢" if g["score"] >= 8 else "🟡"
        print(f"\n  {dot} [{g['score']}/10]  {g['title']}")
        print(f"       {g['market']}  ·  {g['source']}")
        print(f"       {g['summary']}")
        print(f"       {g['url']}")

    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    print()
    if token and chat_id:
        print(f"  Sending {len(top)} alerts to Telegram...")
        if send_telegram(top, markets):
            print("  Telegram →  sent ✓")
    else:
        print("  Telegram →  not configured (add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to .env)")

    if gig_cfg.get("save_locally", True):
        path = save_digest(top)
        print(f"  Saved    →  {path}")

    print(f"\n{hr('═')}\n")


if __name__ == "__main__":
    main()
