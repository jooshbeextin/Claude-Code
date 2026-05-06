#!/usr/bin/env python3
"""
Film Gig Hunter
Monitors NYC & Toronto film industry job boards, scores listings with Claude,
and sends Telegram alerts for relevant production opportunities.
Run on a schedule (cron) to catch new gigs as they post.
"""

import os
import json
import sys
import re
import time
import hashlib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

CACHE_FILE    = Path("gig_cache.json")
CACHE_TTL_DAYS = 30


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


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;",  "&",  text)
    text = re.sub(r"&lt;",   "<",  text)
    text = re.sub(r"&gt;",   ">",  text)
    text = re.sub(r"&quot;", '"',  text)
    text = re.sub(r"&#\d+;", "",   text)
    return " ".join(text.split())


# ─────────────────────────────────────────────────────────────
# Sources
# ─────────────────────────────────────────────────────────────

def build_sources(config: dict) -> list[dict]:
    markets = config.get("film_gigs", {}).get("markets", ["NYC", "Toronto"])
    sources = []

    if "NYC" in markets:
        sources += [
            {
                "name":   "Indeed NYC — Film Production",
                "market": "NYC",
                "url":    "https://www.indeed.com/rss?q=film+production&l=New+York+City%2C+NY&sort=date&fromage=3",
            },
            {
                "name":   "Indeed NYC — Video Crew",
                "market": "NYC",
                "url":    "https://www.indeed.com/rss?q=%22video+production%22+crew&l=New+York%2C+NY&sort=date&fromage=3",
            },
            {
                "name":   "Indeed NYC — Camera Operator",
                "market": "NYC",
                "url":    "https://www.indeed.com/rss?q=camera+operator+freelance&l=New+York+City%2C+NY&sort=date&fromage=3",
            },
            {
                "name":   "Indeed NYC — DP / Gaffer / PA",
                "market": "NYC",
                "url":    "https://www.indeed.com/rss?q=%22director+of+photography%22+OR+gaffer+OR+%22production+assistant%22+film&l=New+York%2C+NY&sort=date&fromage=3",
            },
            {
                "name":   "Indeed NYC — Branded Content",
                "market": "NYC",
                "url":    "https://www.indeed.com/rss?q=%22branded+content%22+OR+%22commercial+production%22&l=New+York%2C+NY&sort=date&fromage=3",
            },
        ]

    if "Toronto" in markets:
        sources += [
            {
                "name":   "Indeed Toronto — Film Production",
                "market": "Toronto",
                "url":    "https://ca.indeed.com/rss?q=film+production&l=Toronto%2C+Ontario&sort=date&fromage=3",
            },
            {
                "name":   "Indeed Toronto — Video Crew",
                "market": "Toronto",
                "url":    "https://ca.indeed.com/rss?q=%22video+production%22+crew&l=Toronto%2C+Ontario&sort=date&fromage=3",
            },
            {
                "name":   "Indeed Toronto — Camera / Videographer",
                "market": "Toronto",
                "url":    "https://ca.indeed.com/rss?q=camera+operator+OR+videographer+freelance&l=Toronto%2C+Ontario&sort=date&fromage=3",
            },
            {
                "name":   "Indeed Toronto — DP / Gaffer / PA",
                "market": "Toronto",
                "url":    "https://ca.indeed.com/rss?q=%22director+of+photography%22+OR+gaffer+OR+%22production+assistant%22+film&l=Toronto%2C+Ontario&sort=date&fromage=3",
            },
            {
                "name":   "Indeed Toronto — Branded / Commercial",
                "market": "Toronto",
                "url":    "https://ca.indeed.com/rss?q=%22branded+content%22+OR+%22commercial+production%22&l=Toronto%2C+Ontario&sort=date&fromage=3",
            },
        ]

    # User-defined custom RSS sources from config.yaml
    for src in config.get("film_gigs", {}).get("custom_rss_sources", []):
        sources.append(src)

    return sources


def fetch_rss(source: dict) -> list[dict]:
    gigs = []
    try:
        req = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; FilmGigHunter/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()

        root    = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = strip_html(item.findtext("description", ""))
            pub   = item.findtext("pubDate", "").strip()
            if not title or not link:
                continue
            gigs.append({
                "title":       title,
                "url":         link,
                "description": desc[:600],
                "published":   pub,
                "source":      source["name"],
                "market":      source["market"],
            })
    except Exception as e:
        print(f"  ⚠  {source['name']}: {e}")
    return gigs


def fetch_all_gigs(config: dict) -> list[dict]:
    sources    = build_sources(config)
    all_gigs   = []
    seen_urls: set[str] = set()

    for source in sources:
        print(f"  Fetching {source['name']}...")
        for gig in fetch_rss(source):
            if gig["url"] not in seen_urls:
                seen_urls.add(gig["url"])
                all_gigs.append(gig)
        time.sleep(0.8)

    return all_gigs


# ─────────────────────────────────────────────────────────────
# Claude Scoring
# ─────────────────────────────────────────────────────────────

SCORE_SYSTEM = """You are a booking coordinator for Ten Four Pictures, a boutique video
production company (Toronto + NYC). You read incoming job postings and evaluate which ones
represent genuine film/video production opportunities worth pursuing."""


def score_batch(client: anthropic.Anthropic, batch: list[dict], config: dict) -> list[dict]:
    gig_cfg    = config.get("film_gigs", {})
    threshold  = gig_cfg.get("min_score", 6)
    roles      = gig_cfg.get("target_roles", [])
    roles_str  = (", ".join(roles) if roles
                  else "DP, Director, Producer, Editor, Gaffer, PA, Camera Op")

    gig_list = "\n\n".join([
        f"GIG {i+1}:\nTitle: {g['title']}\nMarket: {g['market']}\n"
        f"Source: {g['source']}\nDescription: {g['description'][:450]}"
        for i, g in enumerate(batch)
    ])

    prompt = f"""Score each job posting for relevance to Ten Four Pictures.

Ten Four Pictures:
- Boutique video production company, Toronto-based, also active in NYC
- Services: branded content, commercials, music videos, documentaries, live events, post-production
- Seeking: direct client shoots, freelance crew gigs, and production subcontracts
- Key roles: {roles_str}

Scoring scale (1–10):
10 = Branded content/commercial shoot, music video, documentary production
8–9 = Freelance crew call, video production project, short film with pay
6–7 = Production assistant, BTS video, corporate video shoot
4–5 = Photography-adjacent, large streaming/broadcast corporate staff role
1–3 = Unrelated (retail, office, IT, restaurant, etc.)

{gig_list}

Respond ONLY with a valid JSON array — no markdown, no extra text:
[{{"gig":1,"score":8,"summary":"One sentence describing what this gig is"}},...]"""

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

    client      = anthropic.Anthropic(api_key=api_key)
    all_scored  = []
    batch_size  = 5

    for i in range(0, len(gigs), batch_size):
        batch = gigs[i : i + batch_size]
        try:
            scored = score_batch(client, batch, config)
            all_scored.extend(scored)
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
    header = (
        f"🎬 <b>FILM GIG ALERT</b>  ·  {now}\n"
        f"📍 {' + '.join(markets)}  ·  {len(gigs)} new gig{plural}\n"
        f"{'─' * 32}"
    )
    _tg_post(token, chat_id, header)

    for g in gigs:
        dot     = "🟢" if g["score"] >= 8 else "🟡"
        source  = g["source"].split("—")[0].strip()
        msg = (
            f"{dot} <b>{g['title']}</b>\n"
            f"📌 {g['market']}  ·  {source}  ·  {g['score']}/10\n"
            f"📝 {g['summary']}\n"
            f'🔗 <a href="{g["url"]}">View posting</a>'
        )
        try:
            _tg_post(token, chat_id, msg)
        except Exception as e:
            print(f"  ⚠  Telegram send failed for '{g['title']}': {e}")
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

    lines = [
        f"# Film Gig Digest  ·  {datetime.now().strftime('%B %d, %Y %H:%M')}\n\n",
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

    print("\n" + hr("═"))
    print(f"  FILM GIG HUNTER  ·  {datetime.now().strftime('%A, %B %d, %Y  %H:%M')}")
    print(f"  Markets: {', '.join(markets)}  ·  Min score: {threshold}/10")
    print(hr("═") + "\n")

    # ── Cache ──────────────────────────────────────────────────
    cache = prune_cache(load_cache())

    # ── Fetch ──────────────────────────────────────────────────
    print(hr())
    print("  FETCHING LISTINGS")
    print(hr())
    all_gigs = fetch_all_gigs(config)
    print(f"\n  Total fetched:  {len(all_gigs)}")

    # Filter out already-seen gigs
    new_pairs: list[tuple[str, dict]] = []
    for g in all_gigs:
        gid = gig_id(g["url"])
        if gid not in cache.get("seen", {}):
            new_pairs.append((gid, g))

    print(f"  New (unseen):   {len(new_pairs)}")

    if not new_pairs:
        print("\n  Nothing new since last run — all caught up.")
        save_cache(cache)
        print(f"\n{hr('═')}\n")
        return

    # Mark all new as seen before scoring (prevents re-processing on partial failure)
    now_iso = datetime.now().isoformat()
    for gid, _ in new_pairs:
        cache.setdefault("seen", {})[gid] = now_iso
    save_cache(cache)

    gigs_to_score = [g for _, g in new_pairs]

    # ── Score ──────────────────────────────────────────────────
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

    # ── Print ──────────────────────────────────────────────────
    print(f"\n{hr()}")
    print(f"  TOP GIGS  ({len(top)} shown)")
    print(hr())
    for g in top:
        dot = "🟢" if g["score"] >= 8 else "🟡"
        print(f"\n  {dot} [{g['score']}/10]  {g['title']}")
        print(f"       {g['market']}  ·  {g['source']}")
        print(f"       {g['summary']}")
        print(f"       {g['url']}")

    # ── Telegram ───────────────────────────────────────────────
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    print()
    if token and chat_id:
        print(f"  Sending {len(top)} alerts to Telegram...")
        if send_telegram(top, markets):
            print("  Telegram →  sent ✓")
    else:
        print("  Telegram →  not configured (add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to .env)")

    # ── Save digest ────────────────────────────────────────────
    if gig_cfg.get("save_locally", True):
        path = save_digest(top)
        print(f"  Saved    →  {path}")

    print(f"\n{hr('═')}\n")


if __name__ == "__main__":
    main()
