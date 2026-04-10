"""Tambaya scraper."""
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
MAX_PER_FEED = 5
MAX_TOTAL_NEW = 40

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


def url_hash(u): return hashlib.sha256(u.encode()).hexdigest()[:16]
def clean(t): return re.sub(r"<[^>]+>", "", t or "").strip()[:400]


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m: return json.loads(m.group(0))
    return json.loads(text)


def enrich(client, source, title, summary):
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": PROMPT.format(title=title, source=source, summary=summary)}],
    )
    raw = msg.content[0].text
    try:
        return extract_json(raw)
    except Exception as e:
        print(f"  raw response: {raw[:200]}")
        raise


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"): raise SystemExit("no key")
    client = Anthropic()
    conn = init_db(); cur = conn.cursor()
    new_count = 0
    for region, sources in FEEDS.items():
        for source, url in sources.items():
            try: feed = feedparser.parse(url)
            except Exception as e: print(f"[skip] {source}: {e}"); continue
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
                try: data = enrich(client, source, title, summary)
                except Exception as e: print(f"[fail] {title[:50]}: {e}"); continue
                cur.execute("INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?)",
                    (h, link, source, title, summary, entry.get("published", ""), region, json.dumps(data), datetime.now(timezone.utc).isoformat()))
                conn.commit(); new_count += 1
                print(f"[+] {source}: {title[:6
