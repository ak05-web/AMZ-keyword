"""
Lightweight SQLite history store — keeps a local record of every
keyword-research run so you can track trends over time (which
Helium10 does with paid historical volume charts; here it's simpler
but free: we log our own scrape results each time you run a search).
"""

import sqlite3
import datetime
import pandas as pd

DB_PATH = "keyword_history.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keyword_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            seed TEXT,
            keyword TEXT,
            hits INTEGER,
            best_autocomplete_rank INTEGER,
            opportunity_score REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS competitor_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            asin TEXT,
            title TEXT,
            price TEXT,
            rating TEXT,
            review_count TEXT
        )
    """)
    return conn


def save_keyword_run(seed, rows):
    conn = _connect()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO keyword_runs (run_date, seed, keyword, hits, best_autocomplete_rank, opportunity_score) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (now, seed, r["keyword"], r["hits"], r["best_autocomplete_rank"], r["opportunity_score"])
            for r in rows
        ],
    )
    conn.commit()
    conn.close()


def save_competitor_run(data):
    conn = _connect()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO competitor_runs (run_date, asin, title, price, rating, review_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (now, data.get("asin", ""), data.get("title", ""), data.get("price", ""),
         data.get("rating", ""), data.get("review_count", "")),
    )
    conn.commit()
    conn.close()


def get_keyword_history(seed=None):
    conn = _connect()
    if seed:
        df = pd.read_sql_query(
            "SELECT * FROM keyword_runs WHERE seed = ? ORDER BY run_date", conn, params=(seed,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM keyword_runs ORDER BY run_date", conn)
    conn.close()
    return df


def get_competitor_history(asin=None):
    conn = _connect()
    if asin:
        df = pd.read_sql_query(
            "SELECT * FROM competitor_runs WHERE asin = ? ORDER BY run_date", conn, params=(asin,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM competitor_runs ORDER BY run_date", conn)
    conn.close()
    return df


def list_tracked_seeds():
    conn = _connect()
    df = pd.read_sql_query("SELECT DISTINCT seed FROM keyword_runs ORDER BY seed", conn)
    conn.close()
    return df["seed"].tolist()


def list_tracked_asins():
    conn = _connect()
    df = pd.read_sql_query("SELECT DISTINCT asin FROM competitor_runs ORDER BY asin", conn)
    conn.close()
    return df["asin"].tolist()
