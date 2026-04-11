"""Tambaya scraper."""
import os, json, sqlite3, hashlib, time, re
from datetime import datetime, timezone, timedelta
import feedparser
from anthropic import Anthropic

FEEDS = {
    "nigeria": {
        "Sahara Reporters": "https://saharareporters.com/feeds/latest/feed",
        "Sahara Reporters (Google)": "https://news.google.com/rss/search?q=site:saharareporters.com&hl=en-NG&gl=NG&ceid=NG:en",
        "Daily Trust": "https://dailytrust.com/feed/",
        "Daily Trust (Google)": "https://news.google.com/rss/search?q=site:dailytrust.com&hl=en-NG&gl=NG&ceid=NG:en",
        "Linda Ikeji": "https://www.lindaikejisblog.com/feeds/posts/default?alt=rss",
        "Linda Ikeji (Google)": "https://news.google.com/rss/search?q=site:lindaikejisblog.com&hl=en-NG&gl=NG&ceid=NG:en",
        "S2J News": "https://s2jnews.com/feed/",
        "S2J News (Google)": "https://news.google.com/rss/search?q=site:s2jnews.com&hl=en-NG&gl=NG&ceid=NG:en",
        "Premium Times": "https://www.premiumtimesng.com/feed",
        "Premium Times (Google)": "https://news.google.com/rss/search?q=site:premiumtimesng.com&hl=en-NG&gl=NG&ceid=NG:en",
        "Punch": "https://punchng.com/feed/",
        "Punch (Google)": "https://news.google.com/rss/search?q=site:punchng.com&hl=en-NG&gl=NG&ceid=NG:en",
        "Vanguard": "https://www.vanguardngr.com/feed/",
        "Guardian NG": "https://guardian.ng/feed/",
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
        "Reuters (Google)": "https://news.google.com/rss/search?q=site:reuters.com+world&hl=en&gl=US&ceid=US:en",
        "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "Middle East Eye": "https://www.middleeasteye.net/rss",
        "Middle East Eye (Google)": "https://news.google.com/rss/search?q=site:middleeasteye.net&hl=en&gl=US&ceid=US:en",
    },
}
DB = "cache.db"
OUT = "articles.json"
MAX_PER_FEED = 4
MAX_TOTAL_NEW = 36
KEEP_DAYS = 1

PROMPT = """Analyze this news article. Return ONLY a JSON object, nothing else, no markdown.

Title: {title}
Source: {source}
Summary: {summary}

Required JSON shape:
{{"hausa_translation":"...","sentiment":"positive|negative|neutral","region":"nigeria|africa|world","context_check":"verified|needs_context|disputed","critical_questions":["q1","q2","q3"]}}

For critical_questions give 3-5 sharp questions specific to this story, drawing on frames like cui bono, follow the money, missing voices, timing, loaded language, evidence vs assertion, ownership bias."""


def init_db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS articles (url_hash TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT, summary TEXT, published TEXT, region_hint TEXT, enriched TEXT, fetched_at TEXT)")
    c.commit()
    return c


def url_hash(u):
    return hashlib.sha256(u.encode()).hexdigest()[:16]


def clean(t):
    return re.sub(r"<[^>]+>", "", t or "").strip()[:400]


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)


def enrich(client, source, title, summary):
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": PROMPT.format(title=title, source=source, summary=summary)}],
    )
    return extract_json(msg.content[0].text)


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("no key")
    client = Anthropic()
    conn = init_db()
    cur = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    cur.execute("DELETE FROM articles WHERE fetched_at < ?", (cutoff,))
    conn.commit()
    print(f"Pruned articles older than {KEEP_DAYS} day(s)")

    new_count = 0
    for region, sources in FEEDS.items():
        for source, url in sources.items():
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                print(f"[skip] {source}: {e}")
                continue
            for entry in feed.entries[:MAX_PER_FEED]:
                if new_count >= MAX_TOTAL_NEW:
                    break
                link = entry.get("link", "")
                if not link:
                    continue
                h = url_hash(link)
                cur.execute("SELECT 1 FROM articles WHERE url_hash=?", (h,))
                if cur.fetchone():
                    continue
                title = clean(entry.get("title", ""))
                summary = clean(entry.get("summary", "") or entry.get("description", ""))
                if not title:
                    continue
                try:
                    data = enrich(client, source, title, summary)
                except Exception as e:
                    print(f"[fail] {title[:50]}: {e}")
                    continue
                cur.execute(
                    "INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?)",
                    (h, link, source, title, summary, entry.get("published", ""), region, json.dumps(data), datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                new_count += 1
                print(f"[+] {source}: {title[:60]}")
                time.sleep(0.3)

    cur.execute("SELECT url, source, title, summary, published, region_hint, enriched, fetched_at FROM articles ORDER BY fetched_at DESC LIMIT 40")
    out = []
    for row in cur.fetchall():
        try:
            enriched = json.loads(row[6])
        except Exception:
            enriched = {}
        clean_source = re.sub(r"\s*\(Google\)\s*$", "", row[1])
        out.append({"url": row[0], "source": clean_source, "title": row[2], "summary": row[3], "published": row[4], "region_hint": row[5], "fetched_at": row[7], **enriched})
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(out), "articles": out}, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} articles ({new_count} new)")


if __name__ == "__main__":
    main()
