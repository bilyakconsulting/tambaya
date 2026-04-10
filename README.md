# Tambaya

Critical-thinking news aggregator. Read. Question. Then decide.

## Deploy

1. **Create repo**: New public GitHub repo, push these files to `main`.
2. **Add secret**: Repo → Settings → Secrets and variables → Actions → New repository secret. Name: `ANTHROPIC_API_KEY`. Value: your key from console.anthropic.com.
3. **Enable Pages**: Settings → Pages → Source: "Deploy from a branch" → Branch: `main` → Folder: `/ (root)` → Save.
4. **First run**: Actions tab → "Scrape" → Run workflow. Wait ~2 min. It commits `articles.json` and `cache.db`.
5. **Visit**: `https://<you>.github.io/<repo>/`

## Schedule

Cron runs at 05:00, 12:00, 19:00 UTC daily. Edit `.github/workflows/scrape.yml` to change.

## Local test

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
python scraper.py
```

Open `index.html` via a local server (`python -m http.server`) so `fetch()` works.

## Notes

- SQLite cache (`cache.db`) prevents re-enriching the same URL. Committed to repo so state persists across runs.
- Caps: 8 articles per feed, 60 new per run, 200 in output. Tune in `scraper.py`.
- Ad slots: replace the two `<div class="ad">` blocks in `index.html` with your ad code.
- Critical questions are prompts for the reader, not fact-checks.
