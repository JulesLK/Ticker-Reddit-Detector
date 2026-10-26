"""Point d'entrée : une exécution = une collecte quotidienne + recalcul du
signal + régénération du dashboard. Conçu pour tourner sous GitHub Actions
(voir .github/workflows/daily-collect.yml) mais fonctionne aussi en local."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from config import load_config, DB_PATH, DASHBOARD_PATH
from apewisdom import fetch_universe, today_utc_date
import prices as prices_mod
import storage
import signals
import tracking
import dashboard


def _should_run_now(cfg, conn, today) -> bool:
    if os.environ.get("FORCE_RUN") == "1":
        return True
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return True
    # GitHub Actions saute une bonne partie des crons horaires : on collecte au
    # premier passage de la journée après run_time, sans exiger une heure exacte.
    if datetime.now(timezone.utc).hour < cfg.run_time_hour_utc:
        return False
    return not storage.has_successful_collection(conn, today)


def main():
    cfg = load_config()

    today = today_utc_date()

    with storage.get_db(DB_PATH) as conn:
        if not _should_run_now(cfg, conn, today):
            print(
                f"Collecte déjà faite pour {today} ou heure UTC < run_time ({cfg.run_time}). "
                "Rien à faire ce passage-ci."
            )
            return

        try:
            mention_rows = fetch_universe(cfg.universe, cfg.max_pages)
            rows_for_db = [
                {
                    "ticker": r["ticker"],
                    "mentions": r["mentions"],
                    "mentions_24h_ago": r["mentions_24h_ago"],
                    "rank": r["rank"],
                    "upvotes": r["upvotes"],
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
                for r in mention_rows
            ]
            storage.upsert_mentions(conn, today, rows_for_db)
            storage.log_collection(
                conn, today, "success", f"{len(rows_for_db)} tickers collectés", len(rows_for_db)
            )
            print(f"Collecte ApeWisdom OK : {len(rows_for_db)} tickers pour {today}")
        except Exception as exc:
            storage.log_collection(conn, today, "error", str(exc))
            print(f"Collecte ApeWisdom en erreur : {exc}", file=sys.stderr)

        excluded = set(cfg.excluded_tickers)
        all_tickers = [t for t in storage.get_all_tickers(conn) if t not in excluded]
        all_dates = storage.get_distinct_dates(conn)
        earliest_needed = (datetime.now(timezone.utc) - timedelta(days=cfg.baseline_days + cfg.window_days + 5)).strftime(
            "%Y-%m-%d"
        )

        if all_tickers:
            price_tickers = all_tickers + ([cfg.benchmark] if cfg.benchmark not in all_tickers else [])
            print(f"Récupération prix/volume pour {len(price_tickers)} tickers…")
            raw_prices = prices_mod.fetch_price_history(price_tickers, earliest_needed, today)

            for ticker in price_tickers:
                if ticker == cfg.benchmark and ticker not in all_tickers:
                    first_date = all_dates[0] if all_dates else today
                else:
                    mention_dates = [
                        m["date"] for m in storage.get_ticker_mentions_history(conn, ticker)
                    ]
                    if not mention_dates:
                        continue
                    first_date = mention_dates[0]
                series = prices_mod.build_daily_series_with_carry(
                    raw_prices.get(ticker, {}), first_date, today
                )
                if series:
                    storage.upsert_prices(
                        conn, [{**s, "ticker": ticker} for s in series]
                    )

        evaluations = {}
        for ticker in all_tickers:
            mentions_history = storage.get_ticker_mentions_history(conn, ticker)
            price_history = storage.get_ticker_price_history(conn, ticker)
            evaluation = signals.evaluate_ticker(mentions_history, price_history, cfg)
            evaluation.ticker = ticker
            evaluations[ticker] = evaluation

        new_signals = [
            {
                "ticker": t,
                "close": e.price_series[-1]["close"] if e.price_series else None,
                "mentions": e.mentions_series[-1]["mentions"],
                "rank": e.mentions_series[-1]["rank"],
            }
            for t, e in evaluations.items()
            if e.status == "qualifies"
        ]
        if new_signals:
            storage.log_signals(conn, today, new_signals)
        performance = tracking.compute_performance(conn, cfg)

        window_start = (
            datetime.now(timezone.utc) - timedelta(days=cfg.window_days - 1)
        ).strftime("%Y-%m-%d")
        days_collected_global = len(
            [d for d in storage.get_distinct_dates(conn) if d >= window_start]
        )
        latest_snapshot = storage.get_latest_snapshot_tickers(conn, today)
        tracked_count = len(latest_snapshot) if latest_snapshot else len(all_tickers)
        last_collection = storage.get_last_collection(conn)

        html_out = dashboard.render_dashboard(
            cfg, last_collection, days_collected_global, tracked_count, evaluations, performance
        )
        DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_PATH.write_text(html_out, encoding="utf-8")
        print(f"Dashboard régénéré : {DASHBOARD_PATH}")

        qualifying = [t for t, e in evaluations.items() if e.status == "qualifies"]
        print("\n=== Tickers validant toutes les conditions aujourd'hui ===")
        if qualifying:
            for t in qualifying:
                print(f" - {t}")
        else:
            print(" (aucun)")


if __name__ == "__main__":
    main()
