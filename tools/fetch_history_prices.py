"""Récupère les prix Yahoo (yfinance) des tickers d'une base d'historique de
mentions (créée par count_tickers.py) et les range dans price_snapshot, avec
report du dernier cours sur les week-ends / jours fériés (comme src/prices.py).

Usage : python tools/fetch_history_prices.py BASE.db [mentions_cumulees_min] [benchmark]"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import prices  # noqa: E402

BATCH = 200


def main():
    db = sys.argv[1]
    min_total = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    benchmark = sys.argv[3] if len(sys.argv) > 3 else "SPY"
    conn = sqlite3.connect(db)
    start, end = conn.execute("SELECT MIN(date), MAX(date) FROM mentions_snapshot").fetchone()
    tickers = [
        r[0]
        for r in conn.execute(
            "SELECT ticker FROM mentions_snapshot GROUP BY ticker HAVING SUM(mentions) >= ?",
            (min_total,),
        )
    ]
    if benchmark not in tickers:
        tickers.append(benchmark)
    # marge pour les rendements futurs (jusqu'à 30 jours après la dernière mention)
    from datetime import datetime, timedelta
    end_ext = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=40)).strftime("%Y-%m-%d")
    end_ext = min(end_ext, datetime.now().strftime("%Y-%m-%d"))
    print(f"{len(tickers)} tickers, prix de {start} à {end_ext}", flush=True)

    got = 0
    for i in range(0, len(tickers), BATCH):
        chunk = tickers[i: i + BATCH]
        raw = prices.fetch_price_history(chunk, start, end_ext)
        rows = []
        for t in chunk:
            series = prices.build_daily_series_with_carry(raw.get(t, {}), start, end_ext)
            if series:
                got += 1
            rows += [(s["date"], t, s["close"], s["volume"], s["is_weekend_carry"]) for s in series]
        conn.executemany(
            "INSERT OR REPLACE INTO price_snapshot (date, ticker, close, volume, is_weekend_carry) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
        conn.commit()
        print(f"  {min(i + BATCH, len(tickers))}/{len(tickers)} ({got} avec prix)", flush=True)


if __name__ == "__main__":
    main()
