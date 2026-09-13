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
import dashboard


def _should_run_now(cfg) -> bool:
    if os.environ.get("FORCE_RUN") == "1":
        return True
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return True
    now_hour = datetime.now(timezone.utc).hour
    return now_hour == cfg.run_time_hour_utc


def main():
    cfg = load_config()

    if not _should_run_now(cfg):
        print(
            f"Heure actuelle UTC != run_time configuré ({cfg.run_time}). "
            "Rien à faire ce passage-ci (le workflow tourne toutes les heures)."
        )
        return

    today = today_utc_date()

    with storage.get_db(DB_PATH) as conn:
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

        all_tickers = storage.get_all_tickers(conn)
        earliest_needed = (datetime.now(timezone.utc) - timedelta(days=cfg.baseline_days + 5)).strftime(
            "%Y-%m-%d"
        )

        if all_tickers:
            print(f"Récupération prix/volume pour {len(all_tickers)} tickers…")
            raw_prices = prices_mod.fetch_price_history(all_tickers, earliest_needed, today)

            for ticker in all_tickers:
                mention_dates = [
                    m["date"] for m in storage.get_ticker_mentions_history(conn, ticker)
                ]
                if not mention_dates:
                    continue
                series = prices_mod.build_daily_series_with_carry(
                    raw_prices.get(ticker, {}), mention_dates[0], today
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

        days_collected_global = len(storage.get_distinct_dates(conn))
        latest_snapshot = storage.get_latest_snapshot_tickers(conn, today)
        tracked_count = len(latest_snapshot) if latest_snapshot else len(all_tickers)
        last_collection = storage.get_last_collection(conn)

        html_out = dashboard.render_dashboard(
            cfg, last_collection, days_collected_global, tracked_count, evaluations
        )
        DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_PATH.write_text(html_out, encoding="utf-8")
        print(f"Dashboard régénéré : {DASHBOARD_PATH}")

        qualifying = [t for t, e in evaluations.items() if e.status == "qualifies"]
        print("\n=== Tickers validant les 3 conditions aujourd'hui ===")
        if qualifying:
            for t in qualifying:
                print(f" - {t}")
        else:
            print(" (aucun)")


if __name__ == "__main__":
    main()
