"""
RapidAPI provider layer — primary + fallback Amazon data sources.

Why this exists: direct scraping (completion.amazon.in, www.amazon.in)
gets blocked by Amazon's CloudFront/WAF when requests come from cloud
data-center IPs (Streamlit Community Cloud, AWS, etc). RapidAPI
providers run their own infrastructure to get around this reliably,
so this module tries them FIRST, and only falls back to raw scraping
(scraper.py) as a last resort.

HOW TO ADD YOUR KEYS:
Add to .streamlit/secrets.toml (local) or Streamlit Cloud → Settings → Secrets:

    rapidapi_key = "your-single-rapidapi-key-here"

One RapidAPI account key works across ALL RapidAPI-hosted APIs you've
subscribed to (Basic/free plans) — you don't need a separate key per
provider. You just need to click "Subscribe" on each provider's page
on rapidapi.com/hub with your account.

PROVIDERS CONFIGURED BELOW (in fallback order):
1. Real-Time Amazon Data (letscrape) — real-time-amazon-data.p.rapidapi.com
   Free tier: check current limits on RapidAPI (varies, historically ~ a few
   hundred/month on Basic). Endpoints used: /search, /product-details
2. Amazon Online Data API (firstocenka) — used as fallback for search/details
   if provider 1 fails or its quota is exhausted.

Both need you to independently hit "Subscribe" (Basic/free plan) on their
RapidAPI pages before your key will work against them:
- https://rapidapi.com/letscrape-6bRBa3QguO5/api/real-time-amazon-data
- https://rapidapi.com/firstocenka/api/amazon-online-data-api

If a provider's response shape changes (RapidAPI providers update APIs
periodically), adjust the `normalize_search` / `normalize_details`
functions for that provider below — the rest of the app doesn't need
to change since everything downstream reads the normalized shape.
"""

import requests
import streamlit as st

REQUEST_TIMEOUT = 10

COUNTRY_MAP = {
    "amazon.in": "IN",
    "amazon.com": "US",
}


def _get_rapidapi_key():
    return st.secrets.get("rapidapi_key", None)


# ---------------------------------------------------------------
# Provider 1: Real-Time Amazon Data (letscrape / OpenWeb Ninja)
# ---------------------------------------------------------------
def _rta_search(query, marketplace, key):
    host = "real-time-amazon-data.p.rapidapi.com"
    url = f"https://{host}/search"
    params = {
        "query": query,
        "page": "1",
        "country": COUNTRY_MAP.get(marketplace, "IN"),
        "sort_by": "RELEVANCE",
    }
    headers = {"x-rapidapi-host": host, "x-rapidapi-key": key}
    r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    products = data.get("data", {}).get("products", [])

    results = []
    for pos, p in enumerate(products, start=1):
        results.append({
            "position": pos,
            "asin": p.get("asin", ""),
            "title": p.get("product_title", ""),
            "sponsored": bool(p.get("is_amazon_choice") is False and p.get("sponsored", False)),
            "price": p.get("product_price", ""),
            "rating": str(p.get("product_star_rating", "")),
            "review_count": str(p.get("product_num_ratings", "")),
        })
    return results


def _rta_product_details(asin, marketplace, key):
    host = "real-time-amazon-data.p.rapidapi.com"
    url = f"https://{host}/product-details"
    params = {"asin": asin, "country": COUNTRY_MAP.get(marketplace, "IN")}
    headers = {"x-rapidapi-host": host, "x-rapidapi-key": key}
    r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json().get("data", {})

    bullets = data.get("about_product", []) or []
    title = data.get("product_title", "")
    blob = " ".join([title] + bullets).lower()

    import re
    words = re.findall(r"[a-z0-9]+", blob)
    stop = {"the", "and", "for", "with", "your", "this", "that", "from", "are",
            "you", "our", "can", "not", "all", "has", "will", "made", "size"}
    freq = {}
    for w in words:
        if len(w) < 3 or w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    top_terms = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:25]

    photos = data.get("product_photos", []) or []

    return {
        "asin": asin,
        "url": data.get("product_url", ""),
        "title": title,
        "brand": data.get("product_details", {}).get("Brand", "") if isinstance(data.get("product_details"), dict) else "",
        "price": data.get("product_price", ""),
        "rating": str(data.get("product_star_rating", "")),
        "review_count": str(data.get("product_num_ratings", "")),
        "bullets": bullets,
        "top_terms": top_terms,
        "image_count": len(photos),
        "has_aplus": bool(data.get("has_aplus_content", False)),
        "description": data.get("product_description", "") or "",
        "error": None,
    }


# ---------------------------------------------------------------
# Provider 2: Amazon Online Data API (firstocenka) — fallback
# ---------------------------------------------------------------
def _aoda_search(query, marketplace, key):
    host = "amazon-online-data-api.p.rapidapi.com"
    url = f"https://{host}/search"
    params = {"query": query, "geo": COUNTRY_MAP.get(marketplace, "IN")}
    headers = {"x-rapidapi-host": host, "x-rapidapi-key": key}
    r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    products = data.get("results", []) or data.get("products", [])

    results = []
    for pos, p in enumerate(products, start=1):
        if isinstance(p, list):
            continue
        results.append({
            "position": pos,
            "asin": p.get("asin", ""),
            "title": p.get("title", ""),
            "sponsored": bool(p.get("sponsored", False)),
            "price": str(p.get("price", "")),
            "rating": str(p.get("rating", "")),
            "review_count": str(p.get("reviews", "") or p.get("review_count", "")),
        })
    return results


def _aoda_product_details(asin, marketplace, key):
    host = "amazon-online-data-api.p.rapidapi.com"
    url = f"https://{host}/product"
    params = {"asin": asin, "geo": COUNTRY_MAP.get(marketplace, "IN")}
    headers = {"x-rapidapi-host": host, "x-rapidapi-key": key}
    r = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    title = data.get("title", "")
    bullets = data.get("bullet_points", []) or data.get("features", []) or []
    blob = " ".join([title] + bullets).lower()

    import re
    words = re.findall(r"[a-z0-9]+", blob)
    stop = {"the", "and", "for", "with", "your", "this", "that", "from", "are",
            "you", "our", "can", "not", "all", "has", "will", "made", "size"}
    freq = {}
    for w in words:
        if len(w) < 3 or w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    top_terms = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:25]

    return {
        "asin": asin,
        "url": data.get("url", ""),
        "title": title,
        "brand": data.get("brand", ""),
        "price": str(data.get("price", "")),
        "rating": str(data.get("rating", "")),
        "review_count": str(data.get("review_count", "")),
        "bullets": bullets,
        "top_terms": top_terms,
        "image_count": len(data.get("images", []) or []),
        "has_aplus": bool(data.get("has_aplus", False)),
        "description": data.get("description", "") or "",
        "error": None,
    }


# ---------------------------------------------------------------
# Public interface — tries providers in order, falls back on failure
# ---------------------------------------------------------------
SEARCH_PROVIDERS = [
    ("Real-Time Amazon Data", _rta_search),
    ("Amazon Online Data API", _aoda_search),
]

DETAILS_PROVIDERS = [
    ("Real-Time Amazon Data", _rta_product_details),
    ("Amazon Online Data API", _aoda_product_details),
]


def api_search(query, marketplace="amazon.in"):
    """
    Try each configured RapidAPI search provider in order. Returns
    (results, provider_name_used, error_message). If ALL providers
    fail, results is [] and error_message explains the last failure
    so the caller can fall back to raw scraping.
    """
    key = _get_rapidapi_key()
    if not key:
        return [], None, "rapidapi_key secret set nahi hai."

    last_error = None
    for name, fn in SEARCH_PROVIDERS:
        try:
            results = fn(query, marketplace, key)
            if results:
                return results, name, None
            last_error = f"{name}: empty results"
        except Exception as e:
            last_error = f"{name}: {e}"
            continue
    return [], None, last_error


def api_product_details(asin, marketplace="amazon.in"):
    """Same pattern as api_search but for single-ASIN product details."""
    key = _get_rapidapi_key()
    if not key:
        return None, None, "rapidapi_key secret set nahi hai."

    last_error = None
    for name, fn in DETAILS_PROVIDERS:
        try:
            data = fn(asin, marketplace, key)
            if data and data.get("title"):
                return data, name, None
            last_error = f"{name}: empty/incomplete data"
        except Exception as e:
            last_error = f"{name}: {e}"
            continue
    return None, None, last_error


# ---------------------------------------------------------------
# Keyword mining via search results (RapidAPI-only keyword research)
# ---------------------------------------------------------------
import re as _re

_STOPWORDS = {
    "the", "and", "for", "with", "your", "this", "that", "from", "are",
    "you", "our", "can", "not", "all", "has", "will", "made", "size",
    "pack", "set", "new", "amp", "inch", "inches", "pcs", "piece",
}

# Kept small on purpose: each entry here = 1 extra API call against
# your monthly quota. seed alone is always queried first for free.
DEFAULT_MODIFIERS = [
    "best {seed}",
    "{seed} for men",
    "{seed} for women",
    "{seed} gift",
    "cheap {seed}",
    "{seed} pack",
]


def mine_keywords_from_titles(seed, marketplace="amazon.in", modifiers=None, progress_cb=None):
    """
    RapidAPI-only keyword research substitute: queries the /search
    endpoint for the seed + a handful of common modifiers, then mines
    2-4 word phrases out of the real product titles returned. This is
    NOT the same as true autocomplete suggestions (Amazon doesn't
    expose that via any current RapidAPI provider), but it surfaces
    real buyer-facing language actually used in listings for this
    niche — works entirely through RapidAPI, so no cloud-IP blocking.

    Returns (rows, error). rows is [] with an error message if the
    key is missing or every query failed.
    """
    key = _get_rapidapi_key()
    if not key:
        return [], "rapidapi_key secret set nahi hai — is method ke liye RapidAPI key zaroori hai."

    modifiers = modifiers if modifiers is not None else DEFAULT_MODIFIERS
    queries = [seed] + [m.format(seed=seed) for m in modifiers]

    all_titles = []
    any_success = False
    last_error = None
    total = len(queries)

    for i, q in enumerate(queries, start=1):
        try:
            results = None
            for name, fn in SEARCH_PROVIDERS:
                try:
                    results = fn(q, marketplace, key)
                    if results:
                        break
                except Exception as e:
                    last_error = f"{name}: {e}"
                    continue
            if results:
                any_success = True
                all_titles.extend([r["title"] for r in results if r.get("title")])
        except Exception as e:
            last_error = str(e)
        if progress_cb:
            progress_cb(i / total)

    if not any_success:
        return [], last_error or "Koi query successful nahi hui."

    # n-gram mining (2 to 4 word phrases) across all collected titles
    phrase_hits = {}   # phrase -> count of titles it appeared in
    for title in all_titles:
        words = _re.findall(r"[a-zA-Z0-9]+", title.lower())
        words = [w for w in words if w not in _STOPWORDS and len(w) > 1]
        seen_in_this_title = set()
        for n in (2, 3, 4):
            for j in range(len(words) - n + 1):
                phrase = " ".join(words[j:j + n])
                if phrase in seen_in_this_title:
                    continue
                seen_in_this_title.add(phrase)
                phrase_hits[phrase] = phrase_hits.get(phrase, 0) + 1

    rows = []
    for phrase, hits in phrase_hits.items():
        if hits < 2:  # drop one-off noise
            continue
        rows.append({
            "keyword": phrase,
            "word_count": len(phrase.split()),
            "hits": hits,
            "best_autocomplete_rank": 1,  # not applicable for this method
            "opportunity_score": round(hits * 10, 1),
        })
    rows.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return rows[:150], None
