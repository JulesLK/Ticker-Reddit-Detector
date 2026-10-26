"""Suivi des signaux : chaque ticker validé est enregistré (signal_log) avec
son prix du jour ; on mesure ensuite son rendement après N jours calendaires
et on le compare au benchmark (SPY par défaut). C'est le test qui dira si le
screener prédit quoi que ce soit."""

from datetime import datetime, timedelta

import storage


def _plus_days(date_str, n):
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def compute_performance(conn, cfg):
    """Retourne {"rows": [...], "summary": {horizon: {...}}, "verdict": str}.
    Un horizon n'est mesuré que si les prix du ticker ET du benchmark existent
    à la date cible (donc jamais dans le futur)."""

    signals = storage.get_signals(conn)
    rows = []
    excess_by_h = {h: [] for h in cfg.signal_horizons}

    for sig in signals:
        entry = {"signal_date": sig["signal_date"], "ticker": sig["ticker"], "horizons": {}}
        bench_start = storage.get_close(conn, cfg.benchmark, sig["signal_date"])
        for h in cfg.signal_horizons:
            target = _plus_days(sig["signal_date"], h)
            t_end = storage.get_close(conn, sig["ticker"], target)
            b_end = storage.get_close(conn, cfg.benchmark, target)
            if not (sig["close"] and t_end and bench_start and b_end):
                entry["horizons"][h] = None
                continue
            ret = t_end / sig["close"] - 1
            bench_ret = b_end / bench_start - 1
            entry["horizons"][h] = {"ret": ret, "excess": ret - bench_ret}
            excess_by_h[h].append(ret - bench_ret)
        rows.append(entry)

    summary = {}
    for h, vals in excess_by_h.items():
        n = len(vals)
        summary[h] = {
            "n": n,
            "mean_excess": sum(vals) / n if n else None,
            "win_rate": sum(v > 0 for v in vals) / n if n else None,
        }

    enough = [s for s in summary.values() if s["n"] >= cfg.success_min_signals]
    if not enough:
        most = max((s["n"] for s in summary.values()), default=0)
        verdict = (
            f"Pas encore de verdict : {most}/{cfg.success_min_signals} signaux mesurés au minimum."
        )
    elif all(s["win_rate"] >= cfg.success_win_rate for s in enough):
        verdict = "Critère atteint : les signaux battent le benchmark au seuil fixé."
    else:
        verdict = "Critère non atteint : les signaux ne battent pas clairement le benchmark."

    return {"rows": rows, "summary": summary, "verdict": verdict}
