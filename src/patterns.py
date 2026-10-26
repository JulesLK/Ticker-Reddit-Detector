"""Recherche de patterns : parmi les formes d'évolution des mentions Reddit
(pente, accélération, régularité, rang, engagement...), lesquelles précèdent
une hausse ou une baisse du prix par rapport au benchmark ?

Méthode (volontairement stricte, pour ne pas se raconter d'histoires) :
- pour chaque (ticker, date t) on calcule des features à partir des seules
  observations passées (aucune fuite du futur) ;
- on les compare au rendement futur du ticker moins celui du benchmark ;
- pour chaque date on mesure la corrélation de rang (Spearman) entre feature
  et rendement futur sur tous les tickers (l'"IC") ; on regarde sa moyenne et
  sa stabilité d'une date à l'autre ;
- un test de permutation dit si l'IC moyen peut venir du hasard ;
- comme on teste plusieurs features, seuil corrigé (Bonferroni).

Usage : python src/patterns.py [horizon_jours] [mentions_min] [--db chemin.db]"""

import math
import random
import statistics
import sys
from pathlib import Path
from datetime import datetime, timedelta

import storage
from config import DB_PATH, load_config

LOOKBACK = 5  # observations passées utilisées pour les features
FEATURES = {
    "niveau (log mentions)": lambda f: f["level"],
    "pente (dernier / moyenne passée)": lambda f: f["slope"],
    "accélération (pente récente - pente ancienne)": lambda f: f["accel"],
    "irrégularité (écart-type / moyenne)": lambda f: f["cv"],
    "régularité de la montée (part de jours en hausse)": lambda f: f["up_share"],
    "variation de rang (rang gagné)": lambda f: f["rank_gain"],
    "engagement (upvotes / mention)": lambda f: f["engagement"],
    "momentum de prix passé": lambda f: f["past_ret"],
}


def _rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(xs, ys):
    if len(xs) < 8:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def _plus_days(date, n):
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def build_rows(conn, benchmark, horizon, min_median):
    rows = []
    tickers = [r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM mentions_snapshot")]
    last_price_date = conn.execute("SELECT MAX(date) d FROM price_snapshot").fetchone()["d"]
    for t in tickers:
        hist = storage.get_ticker_mentions_history(conn, t)
        if len(hist) < LOOKBACK + 1:
            continue
        if statistics.median(h["mentions"] for h in hist) < min_median:
            continue
        for i in range(LOOKBACK, len(hist)):
            past = hist[i - LOOKBACK: i + 1]
            date = past[-1]["date"]
            target = _plus_days(date, horizon)
            if target > last_price_date:
                continue
            p0, p1 = storage.get_close(conn, t, date), storage.get_close(conn, t, target)
            b0, b1 = storage.get_close(conn, benchmark, date), storage.get_close(conn, benchmark, target)
            pp = storage.get_close(conn, t, past[0]["date"])
            if not (p0 and p1 and b0 and b1 and pp):
                continue
            m = [h["mentions"] for h in past]
            prior_mean = statistics.mean(m[:-1])
            deltas = [b - a for a, b in zip(m, m[1:])]
            half = len(deltas) // 2
            rows.append(
                {
                    "ticker": t,
                    "date": date,
                    "level": math.log1p(m[-1]),
                    "slope": m[-1] / max(prior_mean, 1.0),
                    "accel": statistics.mean(deltas[half:]) - statistics.mean(deltas[:half]),
                    "cv": statistics.pstdev(m) / max(statistics.mean(m), 1.0),
                    "up_share": sum(d > 0 for d in deltas) / len(deltas),
                    "rank_gain": past[0]["rank"] - past[-1]["rank"],
                    "engagement": past[-1]["upvotes"] / max(past[-1]["mentions"], 1),
                    "past_ret": p0 / pp - 1,
                    "excess": (p1 / p0 - 1) - (b1 / b0 - 1),
                }
            )
    return rows


def analyse(rows, n_perm=2000, seed=7):
    random.seed(seed)
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    dates = [d for d, v in by_date.items() if len(v) >= 8]
    out = []
    for name, fn in FEATURES.items():
        ics = []
        for d in dates:
            ic = spearman([fn(r) for r in by_date[d]], [r["excess"] for r in by_date[d]])
            if ic is not None:
                ics.append(ic)
        if len(ics) < 3:
            continue
        mean_ic = statistics.mean(ics)
        # permutation : on mélange les rendements au sein de chaque date
        hits = 0
        for _ in range(n_perm):
            sim = []
            for d in dates:
                ys = [r["excess"] for r in by_date[d]]
                random.shuffle(ys)
                ic = spearman([fn(r) for r in by_date[d]], ys)
                if ic is not None:
                    sim.append(ic)
            if abs(statistics.mean(sim)) >= abs(mean_ic):
                hits += 1
        out.append(
            {
                "feature": name,
                "mean_ic": mean_ic,
                "pos_dates": sum(i > 0 for i in ics),
                "n_dates": len(ics),
                "p_value": (hits + 1) / (n_perm + 1),
            }
        )
    return out, len(dates)


def main():
    args = sys.argv[1:]
    db_path = DB_PATH
    if "--db" in args:
        i = args.index("--db")
        db_path = Path(args[i + 1])
        del args[i: i + 2]
    horizon = int(args[0]) if len(args) > 0 else 5
    min_median = float(args[1]) if len(args) > 1 else 3
    cfg = load_config()
    with storage.get_db(db_path) as conn:
        rows = build_rows(conn, cfg.benchmark, horizon, min_median)
        results, n_dates = analyse(rows)
    print(f"Horizon : +{horizon} jours · tickers avec médiane >= {min_median:g} mentions")
    print(f"Observations : {len(rows)} (ticker x date) sur {n_dates} dates utilisables\n")
    if not results:
        print("Pas assez de données pour analyser.")
        return
    threshold = 0.05 / len(results)
    print(f"{'feature':52s} {'IC moyen':>9s} {'dates +':>8s} {'p-value':>8s}")
    for r in sorted(results, key=lambda r: r["p_value"]):
        flag = "  <== significatif" if r["p_value"] < threshold else ""
        print(
            f"{r['feature']:52s} {r['mean_ic']:+9.3f} {r['pos_dates']:>3d}/{r['n_dates']:<4d} "
            f"{r['p_value']:8.3f}{flag}"
        )
    print(f"\nSeuil de significativité corrigé (Bonferroni, {len(results)} tests) : p < {threshold:.4f}")


if __name__ == "__main__":
    main()
