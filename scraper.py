"""Tambaya scraper: pulls RSS, enriches via Claude, caches in SQLite, writes articles.json."""
import os, json, sqlite3, hashlib, time, re
from datetime import datetime, timezone
import feedparser
from anthropic import Anthropic

FEEDS = {
    "nigeria": {
        "Punch": "https://punchng.com/feed/",
        "Premium Times": "https://www.premiumtimesng.com/feed",
        "Vanguard": "https://www.vanguardngr.com/feed/",
        "Guardian NG": "https://guardian.ng/feed/",
        "Daily Trust": "https://dailytrust.com/feed/",
        "Sahara Reporters": "https://saharareporters.com/feeds/latest/feed",
        "Channels": "https://www.channelstv.com/feed/",
        "TheCable": "https://www.thecable.ng/feed",
        "BusinessDay": "https://businessday.ng/feed/",
        "Leadership": "https://leadership.ng/feed/",
        "Tribune": "https://tribuneonlineng.com/feed/",
        "PM News": "https://pmnewsnigeria.com/feed/",
        "Daily Post": "https://dailypost.ng/feed/",
        "ICIR": "https://www.icirnigeria.org/feed/",
        "HumAngle": "https://humanglemedia.com/feed/",
    },
    "africa": {
        "AllAfrica": "https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf",
        "BBC Africa": "https://feeds.bbci.co.uk/news/world/africa/rss.xml",
    },
    "world": {
        "Reuters": "https://feeds.reuters.com/reuters/worldNews",
        "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    },
}

DB = "cache.db"
OUT = "articles.json"
MAX_PER_FEED = 8
MAX_TOTAL_NEW = 60

PROMPT = """You analyze news for a Nigerian critical-thinking aggregator. Return ONLY valid JSON, no prose.

Article:
Title: {title}
Source: {source}
Summary: {summary}

Return JSON with exactly these keys:
{{
  "hausa_translation": "the headline translated to Hausa",
  "sentiment": "positive" | "negative" | "neutral",
  "region": "nigeria" | "africa" | "world",
  "context_check": "verified" | "needs_context" | "disputed",
  "critical_questions": ["3 to 5 sharp questions tailored to THIS story"]
}}

For critical_questions, draw from these frames where relevant: cui bono (who benefits), follow the money, missing voices, timing (why now), loaded language, evidence vs assertion, ownership bias. Make questions specific to the actual story, not generic."""


def init_db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS articles (
        url_hash TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT,
        summary TEXT, published TEXT, region_hint TEXT, enriched TEXT, fetched_at TEXT
    )""")
    c.commit()
    return c


def url_hash(u): return hashlib.sha256(u.encode()).hexdigest()[:16]


def clean(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()[:500]


def enrich(client, source, title, summary):
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": PROMPT.format(title=title, source=source, summary=summary)}],
    )
    text = msg.content[0].text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    return json.loads(text)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    client = Anthropic(api_key=api_key)
    conn = init_db()
    cur = conn.cursor()
    new_count = 0

    for region, sources in FEEDS.items():
        for source, url in sources.items():
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                print(f"[skip] {source}: {e}"); continue
            for entry in feed.entries[:MAX_PER_FEED]:
                if new_count >= MAX_TOTAL_NEW: break
                link = entry.get("link", "")
                if not link: continue
                h = url_hash(link)
                cur.execute("SELECT 1 FROM articles WHERE url_hash=?", (h,))
                if cur.fetchone(): continue
                title = clean(entry.get("title", ""))
                summary = clean(entry.get("summary", "") or entry.get("description", ""))
                if not title: continue
                try:
                    data = enrich(client, source, title, summary)
                except Exception as e:
                    print(f"[enrich-fail] {title[:50]}: {e}"); continue
                cur.execute(
                    "INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?)",
                    (h, link, source, title, summary, entry.get("published", ""),
                     region, json.dumps(data), datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                new_count += 1
                print(f"[+] {source}: {title[:60]}")
                time.sleep(0.5)

    cur.execute("SELECT url, source, title, summary, published, region_hint, enriched, fetched_at FROM articles ORDER BY fetched_at DESC LIMIT 200")
    out = []
    for row in cur.fetchall():
        try: enriched = json.loads(row[6])
        except: enriched = {}
        out.append({
            "url": row[0], "source": row[1], "title": row[2], "summary": row[3],
            "published": row[4], "region_hint": row[5], "fetched_at": row[7], **enriched,
        })
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(out), "articles": out}, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} articles ({new_count} new)")


if __name__ == "__main__":
    main()
