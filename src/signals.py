"""Coeur de la détection : hausse de mentions progressive (pas de jour qui
domine, anomalie mesurée en z-score propre au ticker) + prix/volume restant
dans la volatilité normale du ticker. Aucune blacklist permanente : un ticker
est réévalué à chaque run à partir de son historique brut, qui n'est jamais
purgé par ce module."""

import statistics
from dataclasses import dataclass, field

MIN_STD_FLOOR = 0.5  # évite qu'une baseline quasi plate déclenche des anomalies sur du bruit


def _mean_std(values):
    if len(values) < 2:
        return (values[0] if values else 0.0), MIN_STD_FLOOR
    mean = statistics.mean(values)
    std = statistics.pstdev(values)
    return mean, max(std, MIN_STD_FLOOR)


def _deltas(values):
    return [values[i] - values[i - 1] for i in range(1, len(values))]


def _zscores(values, mean, std):
    return [(v - mean) / std for v in values]


@dataclass
class TickerEvaluation:
    ticker: str
    status: str  # "qualifies" | "rejected" | "insufficient_history" | "insufficient_price_data"
    days_collected: int
    days_needed: int
    reasons: list = field(default_factory=list)
    is_early_trend: bool = False
    mentions_series: list = field(default_factory=list)
    price_series: list = field(default_factory=list)


def evaluate_ticker(mentions_history, price_history, cfg) -> TickerEvaluation:
    """mentions_history: liste triée par date de {"date","mentions"}.
    price_history: liste triée par date de {"date","close","volume","is_weekend_carry"}
    couvrant les mêmes dates (ou un sous-ensemble)."""

    ticker = None  # rempli par l'appelant si besoin ; on garde la fonction pure
    required_days = cfg.baseline_days

    days_collected = len(mentions_history)

    if days_collected < cfg.early_trend_min_days:
        return TickerEvaluation(
            ticker=ticker,
            status="insufficient_history",
            days_collected=days_collected,
            days_needed=required_days,
            reasons=[f"Historique trop court ({days_collected} jour(s))"],
            mentions_series=mentions_history,
            price_series=price_history,
        )

    if days_collected < required_days:
        # Pas assez pour un signal définitif, mais assez pour juger d'une
        # tendance naissante à mettre en avant sur le dashboard.
        early = _is_progressive(
            [m["mentions"] for m in mentions_history],
            [m["mentions"] for m in mentions_history],  # baseline = tout l'historique dispo
            cfg.anomaly_sensitivity,
        )
        return TickerEvaluation(
            ticker=ticker,
            status="insufficient_history",
            days_collected=days_collected,
            days_needed=required_days,
            reasons=[f"Il manque {required_days - days_collected} jour(s) d'historique"],
            is_early_trend=early["progressive"] and early["net_rise"] > 0,
            mentions_series=mentions_history,
            price_series=price_history,
        )

    baseline_mentions = [m["mentions"] for m in mentions_history[-required_days:]]
    window_mentions = [m["mentions"] for m in mentions_history[-(cfg.window_days + 1):]]

    mention_check = _is_progressive(window_mentions, baseline_mentions, cfg.anomaly_sensitivity)

    reasons = []
    if mention_check["net_rise"] <= 0:
        reasons.append("Pas de hausse nette des mentions sur la fenêtre")
    if not mention_check["progressive"]:
        day = mention_check["worst_day_offset"]
        reasons.append(
            f"Hausse concentrée sur un seul jour (z={mention_check['worst_z']:.1f}, "
            f"jour -{day} de la fenêtre)"
        )

    price_by_date = {p["date"]: p for p in price_history}
    dates_needed = [m["date"] for m in mentions_history[-required_days:]]
    if not all(d in price_by_date for d in dates_needed):
        return TickerEvaluation(
            ticker=ticker,
            status="insufficient_price_data",
            days_collected=days_collected,
            days_needed=required_days,
            reasons=["Historique de prix incomplet pour la période requise"],
            mentions_series=mentions_history,
            price_series=price_history,
        )

    baseline_prices = [price_by_date[d]["close"] for d in dates_needed]
    baseline_volumes = [price_by_date[d]["volume"] for d in dates_needed]
    window_dates = [m["date"] for m in mentions_history[-(cfg.window_days + 1):]]
    window_prices = [price_by_date[d]["close"] for d in window_dates]
    window_volumes = [price_by_date[d]["volume"] for d in window_dates]

    price_check = _is_stable(
        window_prices, baseline_prices, cfg.price_volatility_sensitivity, use_returns=True
    )
    volume_check = _is_stable(
        window_volumes, baseline_volumes, cfg.price_volatility_sensitivity, use_returns=False
    )

    if not price_check["stable"]:
        reasons.append(
            f"Mouvement de prix anormal dans la fenêtre (z={price_check['worst_z']:.1f})"
        )
    if not volume_check["stable"]:
        reasons.append(
            f"Volume anormal dans la fenêtre (z={volume_check['worst_z']:.1f})"
        )

    qualifies = (
        mention_check["net_rise"] > 0
        and mention_check["progressive"]
        and price_check["stable"]
        and volume_check["stable"]
    )

    return TickerEvaluation(
        ticker=ticker,
        status="qualifies" if qualifies else "rejected",
        days_collected=days_collected,
        days_needed=required_days,
        reasons=reasons,
        mentions_series=mentions_history,
        price_series=price_history,
    )


def _is_progressive(window_values, baseline_values, sensitivity):
    baseline_deltas = _deltas(baseline_values)
    mean_d, std_d = _mean_std(baseline_deltas)

    window_deltas = _deltas(window_values)
    z_scores = _zscores(window_deltas, mean_d, std_d)

    net_rise = window_values[-1] - window_values[0]

    if not z_scores:
        return {"progressive": True, "net_rise": net_rise, "worst_z": 0.0, "worst_day_offset": 0}

    worst_idx = max(range(len(z_scores)), key=lambda i: z_scores[i])
    worst_z = z_scores[worst_idx]
    progressive = worst_z <= sensitivity

    return {
        "progressive": progressive,
        "net_rise": net_rise,
        "worst_z": worst_z,
        "worst_day_offset": len(z_scores) - worst_idx,
    }


def _is_stable(window_values, baseline_values, sensitivity, use_returns):
    if use_returns:
        baseline_series = _pct_changes(baseline_values)
        window_series = _pct_changes(window_values)
    else:
        baseline_series = baseline_values
        window_series = window_values

    mean_v, std_v = _mean_std(baseline_series)
    z_scores = [(v - mean_v) / std_v for v in window_series]

    if not z_scores:
        return {"stable": True, "worst_z": 0.0}

    worst_z = max(abs(z) for z in z_scores)
    return {"stable": worst_z <= sensitivity, "worst_z": worst_z}


def _pct_changes(values):
    changes = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev:
            changes.append((values[i] - prev) / prev)
        else:
            changes.append(0.0)
    return changes
