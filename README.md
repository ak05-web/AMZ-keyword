# Amazon Keyword & Competitor Research Tool

Personal-use, password-protected Streamlit tool for Amazon keyword research,
competition analysis, and competitor teardown — built to cover the core
workflows of paid tools like Helium10 (Cerebro, Magnet, Listing Analyzer)
using only free methods (Amazon's public autocomplete endpoint + direct
page scraping). No paid API keys needed.

## Features

1. **Keyword Research** (Magnet-style) — "alphabet soup" method against
   Amazon's autocomplete for `seed + " " + a..z / 0..9`, scored by
   frequency + rank position, with a bar-chart view of top opportunities.
2. **Competition Analyzer** (Cerebro-style, keyword → market) — enter a
   keyword, see the actual page-1 results (organic vs sponsored, price,
   rating, reviews) and a 0-100 difficulty score based on avg top-10
   reviews and sponsored-slot density.
3. **Competitor Teardown** (single ASIN deep-dive) — title, bullets,
   price, rating, reviews, image count, A+ content flag, and a ranked
   term-frequency chart.
4. **Reverse ASIN — Multi** (Cerebro-style, ASIN → keywords) — feed 2-5
   competitor ASINs/URLs at once, see which keywords overlap across all
   of them (the terms most worth targeting because multiple competitors
   independently use them).
5. **Keyword Gap** — your researched keyword list vs. a competitor's
   (or overlap set's) terms — what they use that you're missing.
6. **Listing Quality Audit** (Listing Analyzer-style) — checks title
   length, bullet count/depth, keyword stuffing, A+ content, and image
   count against known best practices, with a 0-100 score. Works on a
   fetched ASIN or manually pasted content.
7. **History tracking** — every keyword research run and every
   competitor scrape is logged to a local SQLite file
   (`keyword_history.db`), so you can pull up past runs and watch metrics
   (like review count) change over time.
8. **CSV export** on every tab.
9. **Password gate** so randoms can't open your hosted app.

## Local setup

```bash
cd amazon-keyword-tool
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml and set your own app_password
streamlit run app.py
```

Open the local URL Streamlit prints (usually `http://localhost:8501`).

## Deploying free (Streamlit Community Cloud)

1. Push this folder to a GitHub repo (secrets.toml is gitignored — don't
   worry, it won't upload).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, click "New app", pick this repo and `app.py` as the entry point.
3. Before/after deploying, go to your app's **Settings → Secrets** and
   paste:
   ```
   app_password = "your-password-here"
   ```
4. Deploy. You'll get a public URL — but nobody can use it without your
   password.

## Notes & limitations

- Amazon's page HTML changes periodically; if competitor/search-page
  scraping starts returning empty results, the CSS selectors in
  `scraper.py` may need small updates.
- This is meant for light, occasional personal use — not high-frequency
  automated scraping. There are small delays built into the loops
  (alphabet-soup, multi-ASIN) to stay gentle on Amazon's endpoints.
  Scraping too fast/too often can trigger Amazon's bot-detection page —
  if a tab suddenly returns empty, wait a bit before retrying.
- "Opportunity score" and "Difficulty score" are heuristics (frequency +
  rank position, or avg reviews + sponsored density), not real
  search-volume/PPC data — no free source gives true Amazon search
  volume or exact CPC.
- `keyword_history.db` (SQLite) lives locally next to the app. If you
  deploy to Streamlit Community Cloud, note that the filesystem there is
  ephemeral — history resets on redeploys/restarts. For persistent
  hosted history you'd eventually want a hosted DB, but for personal use
  running mostly locally this is fine as-is.
- Works for `amazon.in` and `amazon.com`; switch marketplace in the
  sidebar.

## File structure

```
amazon-keyword-tool/
├── app.py                        # Streamlit UI (7 tabs)
├── scraper.py                    # autocomplete, search-results, product-page
│                                  # scraping, scoring, reverse-ASIN, quality audit
├── history.py                    # SQLite-based run history/tracking
├── auth.py                       # password gate
├── requirements.txt
├── .streamlit/
│   ├── config.toml               # theme
│   └── secrets.toml.example      # copy to secrets.toml, don't commit real one
└── .gitignore                    # excludes secrets.toml and keyword_history.db
```
