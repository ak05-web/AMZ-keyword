import io
import pandas as pd
import plotly.express as px
import streamlit as st

from auth import check_password
from scraper import (
    alphabet_soup_keywords,
    scrape_product_listing,
    scrape_search_results,
    competition_score,
    multi_asin_reverse_lookup,
    listing_quality_score,
)
import history

st.set_page_config(
    page_title="Amazon Keyword & Competitor Tool",
    page_icon="📦",
    layout="wide",
)

if not check_password():
    st.stop()

st.title("📦 Amazon Keyword & Competitor Research Tool")
st.caption("Keyword mining • Competition analysis • Reverse ASIN • Listing audit • History tracking — sab CSV me export hota hai.")

with st.sidebar:
    st.header("Settings")
    marketplace = st.selectbox("Marketplace", ["amazon.in", "amazon.com"], index=0)
    st.markdown("---")
    st.markdown(
        "**Tabs:**\n"
        "1. Keyword Research — autocomplete se buyer-search phrases\n"
        "2. Competition Analyzer — kisi keyword pe page-1 kitna tough hai\n"
        "3. Competitor Teardown — single ASIN deep-dive\n"
        "4. Reverse ASIN (Multi) — 2-5 competitors ke common keywords\n"
        "5. Keyword Gap — apni list vs competitor terms\n"
        "6. Listing Quality Audit — apni listing health-check\n"
        "7. History — pichle runs ka trend"
    )
    if st.button("Logout"):
        st.session_state["password_correct"] = False
        st.rerun()

def to_csv_download(df, label, filename):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(label, data=buf.getvalue(), file_name=filename, mime="text/csv")

tabs = st.tabs([
    "🔑 Keyword Research",
    "⚔️ Competition Analyzer",
    "🕵️ Competitor Teardown",
    "🔄 Reverse ASIN (Multi)",
    "📊 Keyword Gap",
    "✅ Listing Quality Audit",
    "📈 History",
])

# ---------------------------------------------------------------
# TAB 1: Keyword Research
# ---------------------------------------------------------------
with tabs[0]:
    st.subheader("Keyword Research (Alphabet Soup Method)")
    seed = st.text_input("Seed keyword (e.g. 'protein powder')", key="seed_kw")
    col_a, col_b = st.columns([1, 1])
    with col_a:
        run_kw = st.button("Find Keywords", type="primary", key="run_kw")
    with col_b:
        test_conn = st.button("🔧 Test Connection (debug)", key="test_conn")

    if test_conn:
        from scraper import get_autocomplete_suggestions
        test_seed = seed.strip() or "protein powder"
        suggestions, info = get_autocomplete_suggestions(test_seed, marketplace=marketplace, debug=True)
        st.write(f"**URL hit:** `{info['url']}`")
        st.write(f"**HTTP status:** `{info['status']}`")
        if info["error"]:
            st.error(f"Error: {info['error']}")
        st.write(f"**Suggestions mile:** {len(suggestions)}")
        if suggestions:
            st.success(f"Working hai! Sample: {suggestions[:5]}")
        else:
            st.warning("Kuch nahi mila — neeche raw response dekho.")
        with st.expander("Raw response (first 300 chars)"):
            st.code(info["raw"] or "(empty)")

    if run_kw and seed.strip():
        progress = st.progress(0.0, text="Autocomplete queries chal rahi hain...")

        def cb(frac):
            progress.progress(min(frac, 1.0), text=f"Autocomplete queries chal rahi hain... {int(frac*100)}%")

        rows = alphabet_soup_keywords(seed.strip(), marketplace=marketplace, progress_cb=cb)
        progress.empty()

        if not rows:
            st.warning("Koi suggestions nahi mile. Seed keyword change karke try karo.")
        else:
            df = pd.DataFrame(rows)
            history.save_keyword_run(seed.strip(), rows)
            st.success(f"{len(df)} unique keyword phrases mile — history me bhi save ho gaya.")

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Keywords", len(df))
            c2.metric("Avg Opportunity Score", round(df["opportunity_score"].mean(), 1))
            c3.metric("2-word phrases", int((df["word_count"] == 2).sum()))

            fig = px.bar(
                df.head(20), x="opportunity_score", y="keyword", orientation="h",
                title="Top 20 Keywords by Opportunity Score", height=550,
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

            st.dataframe(df, use_container_width=True, height=400)
            to_csv_download(df, "⬇️ Download CSV", f"keywords_{seed.strip().replace(' ', '_')}.csv")
            st.session_state["last_keyword_df"] = df
            st.session_state["last_seed"] = seed.strip()
    elif run_kw:
        st.warning("Pehle seed keyword daalo.")

# ---------------------------------------------------------------
# TAB 2: Competition Analyzer
# ---------------------------------------------------------------
with tabs[1]:
    st.subheader("Competition Analyzer — kitna tough hai ye keyword?")
    kw_check = st.text_input("Keyword check karo (exact phrase)", key="comp_check_kw")
    run_comp_check = st.button("Analyze Competition", type="primary", key="run_comp_check")

    if run_comp_check and kw_check.strip():
        with st.spinner("Search results page scan ho rahi hai..."):
            sr = scrape_search_results(kw_check.strip(), marketplace=marketplace)

        if sr.get("error") and not sr["results"]:
            st.error(sr["error"])
        else:
            score = competition_score(sr)
            df = pd.DataFrame(sr["results"])

            c1, c2, c3 = st.columns(3)
            if score:
                c1.metric("Difficulty Score", f"{score['difficulty_score']}/100")
                c2.metric("Avg Top-10 Reviews", score["avg_top10_reviews"])
                c3.metric("Sponsored Slots", f"{score['sponsored_ratio_pct']}%")

                if score["difficulty_score"] >= 65:
                    st.warning("High competition — bahut reviews/ads hain page 1 pe. Long-tail variant try karo.")
                elif score["difficulty_score"] >= 35:
                    st.info("Medium competition — achi listing + kuch reviews ke saath rank ho sakta hai.")
                else:
                    st.success("Low competition — ye keyword achha opportunity lag raha hai.")

            st.dataframe(df, use_container_width=True, height=450)
            to_csv_download(df, "⬇️ Download CSV", f"competition_{kw_check.strip().replace(' ', '_')}.csv")
    elif run_comp_check:
        st.warning("Pehle keyword daalo.")

# ---------------------------------------------------------------
# TAB 3: Competitor Teardown (single ASIN)
# ---------------------------------------------------------------
with tabs[2]:
    st.subheader("Competitor Listing Teardown")
    comp_input = st.text_input("Competitor ASIN ya product URL", key="comp_input")
    run_comp = st.button("Analyze Competitor", type="primary", key="run_comp")

    if run_comp and comp_input.strip():
        with st.spinner("Listing scrape ho rahi hai..."):
            data = scrape_product_listing(comp_input.strip(), marketplace=marketplace)

        if data.get("error"):
            st.error(data["error"])
        else:
            history.save_competitor_run(data)
            st.markdown(f"### {data['title'] or '(title not found)'}")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Price", data["price"] or "—")
            c2.metric("Rating", data["rating"] or "—")
            c3.metric("Reviews", data["review_count"] or "—")
            c4.metric("Images", data["image_count"] or "—")
            c5.metric("A+ Content", "Yes" if data["has_aplus"] else "No")

            st.markdown("**Bullet Points:**")
            for b in data["bullets"]:
                st.write(f"- {b}")

            st.markdown("**Top Terms (frequency in title + bullets):**")
            term_df = pd.DataFrame(data["top_terms"], columns=["term", "frequency"])
            fig = px.bar(term_df.head(15), x="frequency", y="term", orientation="h", height=450)
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(term_df, use_container_width=True, height=350)

            to_csv_download(term_df, "⬇️ Download Terms CSV", f"competitor_{data['asin']}_terms.csv")
            st.session_state["last_competitor_terms"] = set(term_df["term"])
            st.session_state["last_competitor_asin"] = data["asin"]
    elif run_comp:
        st.warning("Pehle ASIN ya URL daalo.")

# ---------------------------------------------------------------
# TAB 4: Reverse ASIN Multi
# ---------------------------------------------------------------
with tabs[3]:
    st.subheader("Reverse ASIN — Multiple Competitors (Cerebro-style)")
    st.caption("2-5 competitor ASINs/URLs daalo (ek line me ek), overlapping keywords dekho jo sabki listing me common hain.")
    asin_block = st.text_area("ASINs / URLs (one per line)", height=120, key="multi_asin_block")
    run_multi = st.button("Run Reverse ASIN", type="primary", key="run_multi")

    if run_multi and asin_block.strip():
        asin_list = [a.strip() for a in asin_block.strip().splitlines() if a.strip()][:5]
        with st.spinner(f"{len(asin_list)} listings scrape ho rahi hain..."):
            result = multi_asin_reverse_lookup(asin_list, marketplace=marketplace)

        errors = [l for l in result["listings"] if l.get("error")]
        for e in errors:
            st.error(f"{e['asin']}: {e['error']}")

        ok_listings = [l for l in result["listings"] if not l.get("error")]
        if ok_listings:
            st.markdown("**Listings analyzed:**")
            summary_df = pd.DataFrame([
                {"asin": l["asin"], "title": l["title"][:80], "price": l["price"], "rating": l["rating"]}
                for l in ok_listings
            ])
            st.dataframe(summary_df, use_container_width=True)

            overlap_df = pd.DataFrame(result["overlap"])
            st.markdown("**Overlapping Keywords Across Competitors:**")
            st.dataframe(overlap_df, use_container_width=True, height=400)
            to_csv_download(overlap_df, "⬇️ Download Overlap CSV", "reverse_asin_overlap.csv")
            st.session_state["last_competitor_terms"] = set(overlap_df["term"])
            st.session_state["last_competitor_asin"] = ", ".join([l["asin"] for l in ok_listings])
    elif run_multi:
        st.warning("Kam se kam ek ASIN/URL daalo.")

# ---------------------------------------------------------------
# TAB 5: Keyword Gap
# ---------------------------------------------------------------
with tabs[4]:
    st.subheader("Keyword Gap — Tumhari listing vs Competitor(s)")
    st.caption(
        "Pehle 'Keyword Research' chalao, phir 'Competitor Teardown' ya 'Reverse ASIN (Multi)' chalao. "
        "Fir yahan gap dikhega."
    )

    have_kw = "last_keyword_df" in st.session_state
    have_comp = "last_competitor_terms" in st.session_state

    if not have_kw or not have_comp:
        st.info("Pehle Keyword Research aur Competitor/Reverse-ASIN tabs dono run karo.")
    else:
        my_keywords_blob = " ".join(st.session_state["last_keyword_df"]["keyword"].tolist()).lower()
        comp_terms = st.session_state["last_competitor_terms"]

        missing = sorted([t for t in comp_terms if t not in my_keywords_blob])
        gap_df = pd.DataFrame({"missing_term": missing})

        st.success(
            f"Competitor(s) ({st.session_state.get('last_competitor_asin', '?')}) "
            f"ke {len(comp_terms)} terms me se {len(missing)} tumhari keyword list me missing hain."
        )
        st.dataframe(gap_df, use_container_width=True, height=400)
        to_csv_download(gap_df, "⬇️ Download Gap CSV", "keyword_gap.csv")

# ---------------------------------------------------------------
# TAB 6: Listing Quality Audit
# ---------------------------------------------------------------
with tabs[5]:
    st.subheader("Listing Quality Audit")
    st.caption("Apne product ka ASIN/URL daalo, ya manually title/bullets paste karo.")

    audit_mode = st.radio("Mode", ["Fetch from ASIN/URL", "Manual paste"], horizontal=True)

    if audit_mode == "Fetch from ASIN/URL":
        own_input = st.text_input("Apna ASIN ya product URL", key="own_asin")
        run_audit = st.button("Run Audit", type="primary", key="run_audit_fetch")
        if run_audit and own_input.strip():
            with st.spinner("Listing fetch ho rahi hai..."):
                data = scrape_product_listing(own_input.strip(), marketplace=marketplace)
            if data.get("error"):
                st.error(data["error"])
            else:
                result = listing_quality_score(
                    data["title"], data["bullets"], data.get("description", ""),
                    data.get("image_count", 0), data.get("has_aplus", False),
                )
                st.metric("Listing Quality Score", f"{result['percent']}/100")
                for check, status, note in result["checks"]:
                    icon = {"good": "✅", "warn": "⚠️", "bad": "❌"}[status]
                    st.write(f"{icon} **{check}**: {note}")
    else:
        title_in = st.text_input("Title", key="manual_title")
        bullets_in = st.text_area("Bullets (one per line)", height=150, key="manual_bullets")
        desc_in = st.text_area("Description (optional)", key="manual_desc")
        img_count_in = st.number_input("Image count", min_value=0, max_value=20, value=0)
        aplus_in = st.checkbox("Has A+ Content?")
        run_audit_manual = st.button("Run Audit", type="primary", key="run_audit_manual")
        if run_audit_manual:
            bullets_list = [b.strip() for b in bullets_in.splitlines() if b.strip()]
            result = listing_quality_score(title_in, bullets_list, desc_in, img_count_in, aplus_in)
            st.metric("Listing Quality Score", f"{result['percent']}/100")
            for check, status, note in result["checks"]:
                icon = {"good": "✅", "warn": "⚠️", "bad": "❌"}[status]
                st.write(f"{icon} **{check}**: {note}")

# ---------------------------------------------------------------
# TAB 7: History
# ---------------------------------------------------------------
with tabs[6]:
    st.subheader("History — Pichle Runs Ka Trend")

    seeds = history.list_tracked_seeds()
    asins = history.list_tracked_asins()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Keyword Research History**")
        if seeds:
            pick_seed = st.selectbox("Seed choose karo", seeds)
            kdf = history.get_keyword_history(pick_seed)
            st.dataframe(kdf, use_container_width=True, height=300)
            to_csv_download(kdf, "⬇️ Download History CSV", f"history_{pick_seed}.csv")
        else:
            st.info("Abhi tak koi keyword research history nahi hai.")

    with col2:
        st.markdown("**Competitor Tracking History**")
        if asins:
            pick_asin = st.selectbox("ASIN choose karo", asins)
            cdf = history.get_competitor_history(pick_asin)
            st.dataframe(cdf, use_container_width=True, height=300)
            if len(cdf) > 1:
                cdf["review_count_num"] = cdf["review_count"].str.extract(r"([\d,]+)")[0].str.replace(",", "").astype(float)
                fig = px.line(cdf, x="run_date", y="review_count_num", title=f"{pick_asin} — Review Count Over Time", markers=True)
                st.plotly_chart(fig, use_container_width=True)
            to_csv_download(cdf, "⬇️ Download History CSV", f"history_{pick_asin}.csv")
        else:
            st.info("Abhi tak koi competitor tracking history nahi hai.")
