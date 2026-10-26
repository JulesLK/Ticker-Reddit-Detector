"""Transforme les posts extraits (RS_YYYY-MM.jsonl.gz) en historique quotidien
de mentions par ticker, rangé dans une base SQLite au MÊME schéma que
data/reddit_mentions.db (pour pouvoir réutiliser src/patterns.py tel quel).

Un ticker est compté une fois par post qui le cite :
- cashtag ($GME) : toujours accepté si le ticker existe ;
- ticker nu en majuscules (GME) : accepté s'il existe ET si ce n'est pas un
  mot courant. Un mot est jugé courant si, dans le corpus, il apparaît bien
  plus souvent en minuscules qu'en majuscules (ex. "all", "are", "now").

Usage : python tools/count_tickers.py DOSSIER_POSTS BASE_SORTIE.db"""

import glob
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

SEC_TICKERS = "/tmp/sec.json"  # https://www.sec.gov/files/company_tickers.json
JARGON = {
    "DD", "YOLO", "ATH", "CEO", "CFO", "COO", "USA", "IPO", "ETF", "FOMO", "EPS", "GDP",
    "FED", "IMO", "TLDR", "LOL", "WSB", "OTM", "ITM", "ATM", "IV", "PT", "ER", "PM", "AH",
    "SEC", "FDA", "CPI", "IRS", "NYSE", "TA", "FD", "FDS", "RH", "EV", "AI", "UK", "EU",
    "US", "OP", "LMAO", "WTF", "RIP", "PSA", "EDIT", "TIL", "ELI", "FUD", "MOASS", "ROI",
    "SPAC", "IRA", "HODL", "BTC", "ETH", "USD", "EUR", "GG", "BS", "TD", "PE", "PS",
}
CASHTAG = re.compile(r"\$([A-Za-z]{1,5})\b")
UPPER = re.compile(r"\b([A-Z]{2,5})\b")
LOWER = re.compile(r"\b([a-z]{2,5})\b")


def load_universe():
    d = json.load(open(SEC_TICKERS))
    return {v["ticker"].upper() for v in d.values() if v["ticker"].isalpha()}


def iter_posts(folder):
    for path in sorted(glob.glob(f"{folder}/RS_*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                yield json.loads(line)


def main(folder, out_db):
    universe = load_universe()

    # 1re passe : fréquences minuscules / majuscules pour repérer les mots courants
    upper, lower = Counter(), Counter()
    for p in iter_posts(folder):
        txt = p["title"]
        upper.update(w for w in UPPER.findall(txt) if w in universe)
        lower.update(w.upper() for w in LOWER.findall(txt) if w.upper() in universe)
    common = {
        t for t in universe
        if lower[t] > 0.25 * max(upper[t], 1) or t in JARGON
    }
    print(f"{len(universe)} tickers connus, {len(common)} jugés mots courants/jargon", flush=True)

    per_day = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # date -> ticker -> [posts, score]
    n_posts = 0
    for p in iter_posts(folder):
        if not p.get("t"):
            continue
        n_posts += 1
        date = datetime.fromtimestamp(int(p["t"]), tz=timezone.utc).strftime("%Y-%m-%d")
        text = p["title"] + " " + p["text"]
        found = {c.upper() for c in CASHTAG.findall(text) if c.upper() in universe}
        found |= {w for w in UPPER.findall(p["title"]) if w in universe and w not in common}
        score = max(int(p.get("score") or 0), 0)
        for t in found:
            cell = per_day[date][t]
            cell[0] += 1
            cell[1] += score

    conn = sqlite3.connect(out_db)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mentions_snapshot (
            date TEXT NOT NULL, ticker TEXT NOT NULL, mentions INTEGER NOT NULL,
            mentions_24h_ago INTEGER, rank INTEGER, upvotes INTEGER, collected_at TEXT NOT NULL,
            PRIMARY KEY (date, ticker));
        CREATE TABLE IF NOT EXISTS price_snapshot (
            date TEXT NOT NULL, ticker TEXT NOT NULL, close REAL, volume INTEGER,
            is_weekend_carry INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (date, ticker));
        DELETE FROM mentions_snapshot;
        """
    )
    rows = []
    for date, tick in per_day.items():
        ranked = sorted(tick.items(), key=lambda kv: -kv[1][0])
        for rank, (t, (m, s)) in enumerate(ranked, 1):
            rows.append((date, t, m, None, rank, s, "history"))
    conn.executemany("INSERT INTO mentions_snapshot VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    print(f"{n_posts} posts -> {len(rows)} lignes (date, ticker) sur {len(per_day)} jours", flush=True)
    top = conn.execute(
        "SELECT ticker, SUM(mentions) s FROM mentions_snapshot GROUP BY ticker ORDER BY s DESC LIMIT 15"
    ).fetchall()
    print("Top tickers :", top)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
