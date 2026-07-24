"""
Core scraping + scoring logic.

IMPORTANT: This hits Amazon's public autocomplete endpoint and public
product pages directly (no RapidAPI key needed). It's meant for light,
personal, occasional use — not high-frequency automated scraping.
Amazon's page HTML changes often, so selectors here are best-effort
and may need small tweaks over time.
"""

import re
import time
import string
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}

DOMAIN_MAP = {
    "amazon.in": "completion.amazon.in",
    "amazon.com": "completion.amazon.com",
}


def get_autocomplete_suggestions(prefix, marketplace="amazon.in", timeout=6, debug=False):
    """Fetch raw autocomplete suggestions for a single prefix string.
    If debug=True, returns (suggestions, debug_info) instead of just
    the list — used by the UI to show why a query returned nothing."""
    completion_host = DOMAIN_MAP.get(marketplace, "completion.amazon.in")
    url = f"https://{completion_host}/api/2017/suggestions"
    params = {
        "limit": 11,
        "prefix": prefix,
        "alias": "aps",
        "site-variant": "desktop",
        "mkt": "44571" if marketplace == "amazon.in" else "1",
    }
    info = {"url": url, "status": None, "error": None, "raw": None}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        info["status"] = r.status_code
        info["raw"] = r.text[:300]
        r.raise_for_status()
        data = r.json()
        sugg = data.get("suggestions", [])
        result = [s.get("value", "") for s in sugg if s.get("value")]
        return (result, info) if debug else result
    except Exception as e:
        info["error"] = str(e)
        return ([], info) if debug else []


def alphabet_soup_keywords(seed, marketplace="amazon.in", extra_chars=True, progress_cb=None):
    """
    Classic 'alphabet soup' method: query seed+" "+letter for a-z (and
    optionally 0-9), collect every unique suggestion, and score by how
    often + how early each phrase appears across all the queries.
    Returns a list of dicts: keyword, hits, best_rank, score
    """
    chars = list(string.ascii_lowercase)
    if extra_chars:
        chars += list(string.digits)

    seen = {}
    total = len(chars) + 1  # +1 for the bare seed query
    done = 0

    # bare seed first
    for pos, kw in enumerate(get_autocomplete_suggestions(seed, marketplace)):
        entry = seen.setdefault(kw, {"hits": 0, "best_rank": 999})
        entry["hits"] += 1
        entry["best_rank"] = min(entry["best_rank"], pos)
    done += 1
    if progress_cb:
        progress_cb(done / total)

    for ch in chars:
        prefix = f"{seed} {ch}"
        suggestions = get_autocomplete_suggestions(prefix, marketplace)
        for pos, kw in enumerate(suggestions):
            entry = seen.setdefault(kw, {"hits": 0, "best_rank": 999})
            entry["hits"] += 1
            entry["best_rank"] = min(entry["best_rank"], pos)
        done += 1
        if progress_cb:
            progress_cb(done / total)
        time.sleep(0.15)  # gentle pacing, avoid hammering the endpoint

    rows = []
    for kw, meta in seen.items():
        # Score: more hits (appears across multiple prefixes) = more
        # "real"; lower best_rank (shows up high in a suggestion list)
        # = stronger buyer-intent signal. This is a heuristic proxy,
        # not real search volume (no free API gives true volume).
        score = meta["hits"] * 10 - meta["best_rank"]
        rows.append({
            "keyword": kw,
            "word_count": len(kw.split()),
            "hits": meta["hits"],
            "best_autocomplete_rank": meta["best_rank"] + 1,
            "opportunity_score": round(score, 1),
        })

    rows.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return rows


def scrape_search_results(keyword, marketplace="amazon.in", max_results=20, timeout=8):
    """
    Scrape Amazon's search results page for a keyword — this is the
    'Cerebro-style' competition view: who's ranking, sponsored vs
    organic, price/rating/review spread. Used to gauge how hard a
    keyword is to break into page 1 for.
    """
    url = f"https://www.{marketplace}/s"
    params = {"k": keyword}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"Search page fetch fail hua: {e}", "results": []}

    soup = BeautifulSoup(r.text, "lxml")
    cards = soup.select("div[data-component-type='s-search-result']")

    results = []
    for pos, card in enumerate(cards[:max_results], start=1):
        asin = card.get("data-asin", "")
        card_text_snippet = card.get_text(" ").lower()[:300]
        is_sponsored = "sponsored" in card_text_snippet

        title_el = card.select_one("h2 span") or card.select_one("h2 a span")
        title = title_el.get_text(strip=True) if title_el else ""

        price_el = card.select_one(".a-price .a-offscreen")
        price = price_el.get_text(strip=True) if price_el else ""

        rating_el = card.select_one("span[aria-label*='out of 5 stars']")
        rating = rating_el.get("aria-label", "").replace(" out of 5 stars", "") if rating_el else ""

        review_el = card.select_one("span[aria-label] + span.a-size-base") or card.select_one(
            "a span.a-size-base.s-underline-text"
        )
        review_count = review_el.get_text(strip=True) if review_el else ""

        if not asin and not title:
            continue

        results.append({
            "position": pos,
            "asin": asin,
            "title": title,
            "sponsored": is_sponsored,
            "price": price,
            "rating": rating,
            "review_count": review_count,
        })

    if not results:
        return {
            "error": "Koi result parse nahi hua — Amazon ka page structure change hua ho sakta hai, ya bot-check trigger hua.",
            "results": [],
        }

    return {"error": None, "results": results}


def competition_score(search_result):
    """
    Heuristic competition score for a keyword based on its search
    results page: more reviews + higher ratings among top organic
    listings + more sponsored slots = harder keyword to break into.
    Returns a 0-100 'difficulty' score (higher = harder).
    """
    results = search_result.get("results", [])
    if not results:
        return None

    organic = [r for r in results if not r["sponsored"]][:10]
    if not organic:
        organic = results[:10]

    review_counts = []
    for r in organic:
        digits = re.sub(r"[^\d]", "", r.get("review_count", "") or "")
        if digits:
            review_counts.append(int(digits))

    avg_reviews = sum(review_counts) / len(review_counts) if review_counts else 0
    sponsored_ratio = sum(1 for r in results if r["sponsored"]) / len(results)

    # normalize: 1000+ avg reviews among top10 = very saturated
    review_component = min(avg_reviews / 1000, 1.0) * 70
    sponsored_component = sponsored_ratio * 30
    score = round(review_component + sponsored_component, 1)
    return {
        "difficulty_score": score,
        "avg_top10_reviews": round(avg_reviews),
        "sponsored_ratio_pct": round(sponsored_ratio * 100, 1),
    }


def multi_asin_reverse_lookup(asin_list, marketplace="amazon.in"):
    """
    Scrape multiple competitor ASINs and find overlapping / common
    top-terms across them -- the Cerebro-style 'what do all my
    competitors rank for that I might be missing' view.
    """
    all_data = []
    term_doc_freq = {}  # term -> set of asins it appeared in
    term_total_freq = {}  # term -> summed frequency across listings

    for asin in asin_list:
        data = scrape_product_listing(asin, marketplace=marketplace)
        if data.get("error"):
            all_data.append({"asin": asin, "error": data["error"]})
            continue
        all_data.append(data)
        for term, freq in data.get("top_terms", []):
            term_doc_freq.setdefault(term, set()).add(data["asin"])
            term_total_freq[term] = term_total_freq.get(term, 0) + freq
        time.sleep(0.3)

    overlap_rows = []
    for term, asins in term_doc_freq.items():
        overlap_rows.append({
            "term": term,
            "num_competitors_using": len(asins),
            "total_frequency": term_total_freq[term],
        })
    overlap_rows.sort(key=lambda x: (x["num_competitors_using"], x["total_frequency"]), reverse=True)

    return {"listings": all_data, "overlap": overlap_rows}


def listing_quality_score(title, bullets, description="", image_count=0, has_aplus=False):
    """
    Rough Listing Quality checklist scorer (like Helium10's Listing
    Analyzer / Frankenstein-lite) -- flags common on-page SEO issues
    that hurt page-1 ranking chances.
    """
    checks = []
    score = 0
    max_score = 0

    max_score += 20
    title_len = len(title or "")
    if 80 <= title_len <= 200:
        score += 20
        checks.append(("Title length", "good", f"{title_len} chars"))
    elif title_len > 0:
        score += 10
        checks.append(("Title length", "warn", f"{title_len} chars — 80-200 range is safer"))
    else:
        checks.append(("Title length", "bad", "No title found"))

    max_score += 20
    n_bullets = len(bullets or [])
    if n_bullets >= 5:
        score += 20
        checks.append(("Bullet count", "good", f"{n_bullets} bullets"))
    elif n_bullets > 0:
        score += 10
        checks.append(("Bullet count", "warn", f"Only {n_bullets}/5 bullets used"))
    else:
        checks.append(("Bullet count", "bad", "No bullets found"))

    max_score += 20
    short_bullets = [b for b in (bullets or []) if len(b) < 50]
    if bullets and not short_bullets:
        score += 20
        checks.append(("Bullet depth", "good", "All bullets are detailed (50+ chars)"))
    elif bullets:
        score += 8
        checks.append(("Bullet depth", "warn", f"{len(short_bullets)} bullet(s) are thin (<50 chars)"))
    else:
        checks.append(("Bullet depth", "bad", "No bullets to evaluate"))

    max_score += 15
    words = re.findall(r"[a-zA-Z]+", (title or "").lower())
    repeats = {}
    for w in words:
        if len(w) > 3:
            repeats[w] = repeats.get(w, 0) + 1
    stuffed = [w for w, c in repeats.items() if c >= 3]
    if not stuffed:
        score += 15
        checks.append(("Keyword stuffing", "good", "No obvious repetition in title"))
    else:
        checks.append(("Keyword stuffing", "bad", f"Repeated 3+ times: {', '.join(stuffed)}"))

    max_score += 15
    if has_aplus:
        score += 15
        checks.append(("A+ Content", "good", "A+ content detected"))
    elif description:
        score += 8
        checks.append(("A+ Content", "warn", "Only plain description, no A+ content"))
    else:
        checks.append(("A+ Content", "bad", "No description or A+ content"))

    max_score += 10
    if image_count >= 6:
        score += 10
        checks.append(("Image count", "good", f"{image_count} images"))
    elif image_count > 0:
        score += 5
        checks.append(("Image count", "warn", f"Only {image_count} images — aim for 6+"))
    else:
        checks.append(("Image count", "bad", "No image count available"))

    pct = round((score / max_score) * 100) if max_score else 0
    return {"percent": pct, "checks": checks}


def extract_asin(text):
    """Pull an ASIN out of a raw ASIN string or a full product URL."""
    text = text.strip()
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", text)
    if m:
        return m.group(1)
    m = re.search(r"\b([A-Z0-9]{10})\b", text)
    if m:
        return m.group(1)
    return None


def scrape_product_listing(asin_or_url, marketplace="amazon.in", timeout=8):
    """
    Scrape a single product page for title, bullets, price, rating,
    review count -- used for competitor analysis / keyword extraction.
    """
    asin = extract_asin(asin_or_url)
    if not asin:
        return {"error": "Valid ASIN ya product URL nahi mila."}

    url = f"https://www.{marketplace}/dp/{asin}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        return {"error": f"Page fetch fail hua: {e}"}

    soup = BeautifulSoup(r.text, "lxml")

    def safe_text(sel):
        el = soup.select_one(sel)
        return el.get_text(strip=True) if el else ""

    title = safe_text("#productTitle")

    bullets = []
    for li in soup.select("#feature-bullets ul li"):
        t = li.get_text(strip=True)
        if t:
            bullets.append(t)

    price = (
        safe_text(".a-price .a-offscreen")
        or safe_text("#priceblock_ourprice")
        or safe_text("#priceblock_dealprice")
    )

    rating = safe_text("span[data-hook='rating-out-of-text']") or safe_text(
        "i.a-icon-star span"
    )
    review_count = safe_text("#acrCustomerReviewText")

    brand = safe_text("#bylineInfo")

    # image count: count thumbnail entries in the image block
    image_count = len(soup.select("#altImages li.imageThumbnail")) or len(
        soup.select("#imageBlock img")
    )

    # A+ content presence
    has_aplus = bool(soup.select_one("#aplus, #aplus_feature_div"))

    description = safe_text("#productDescription")

    # crude backend-ish keyword extraction: title + bullets tokenized
    blob = " ".join([title] + bullets).lower()
    words = re.findall(r"[a-z0-9]+", blob)
    stop = {
        "the", "and", "for", "with", "your", "this", "that", "from", "are",
        "you", "our", "can", "not", "all", "has", "will", "made", "size",
    }
    freq = {}
    for w in words:
        if len(w) < 3 or w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    top_terms = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:25]

    return {
        "asin": asin,
        "url": url,
        "title": title,
        "brand": brand,
        "price": price,
        "rating": rating,
        "review_count": review_count,
        "bullets": bullets,
        "top_terms": top_terms,
        "image_count": image_count,
        "has_aplus": has_aplus,
        "description": description,
        "error": None,
    }
