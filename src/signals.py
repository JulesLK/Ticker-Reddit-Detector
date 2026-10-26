"""Coeur de la détection : hausse de mentions progressive (pas de jour qui
domine, anomalie mesurée en z-score propre au ticker), progression du
classement ApeWisdom elle aussi progressive, qualité d'engagement
(upvotes/mentions) qui ne s'effondre pas, et prix/volume restant dans la
volatilité normale du ticker. Aucune blacklist permanente : un ticker est
réévalué à chaque run à partir de son historique brut, qui n'est jamais
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
    rank_start: int = None
    rank_end: int = None
    engagement_window_avg: float = None
    engagement_baseline_avg: float = None


def _smooth(values, n):
    """Moyenne glissante arrière sur n points (moins au tout début)."""
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - n + 1): i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def _rise_check(raw_window, smooth_window, cfg):
    """Volume minimal et amplitude minimale de la hausse (sur mentions lissées)."""
    median_mentions = statistics.median(raw_window) if raw_window else 0
    rise_ratio = smooth_window[-1] / max(smooth_window[0], 1.0) if smooth_window else 0.0
    return {
        "enough_mentions": median_mentions >= cfg.min_median_mentions,
        "median_mentions": median_mentions,
        "big_enough": rise_ratio >= cfg.min_rise_ratio,
        "rise_ratio": rise_ratio,
    }


def evaluate_ticker(mentions_history, price_history, cfg) -> TickerEvaluation:
    """mentions_history: liste triée par date de {"date","mentions","rank","upvotes"}.
    price_history: liste triée par date de {"date","close","volume","is_weekend_carry"}
    couvrant les mêmes dates (ou un sous-ensemble).

    Historique requis pour un signal complet : baseline_days (juste avant la
    fenêtre) + window_days + 1 points. Mentions et rang sont lissés sur
    smoothing_days avant toute détection (effet week-end)."""

    ticker = None  # rempli par l'appelant si besoin ; on garde la fonction pure
    window_points = cfg.window_days + 1
    required_days = cfg.baseline_days + window_points

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

    raw_mentions = [m["mentions"] for m in mentions_history]
    smooth_mentions = _smooth(raw_mentions, cfg.smoothing_days)
    smooth_rank_scores = _smooth([-m["rank"] for m in mentions_history], cfg.smoothing_days)

    if days_collected < required_days:
        # Pas assez pour un signal définitif, mais assez pour juger d'une
        # tendance naissante à mettre en avant sur le dashboard.
        early = _is_progressive(smooth_mentions, smooth_mentions, cfg.anomaly_sensitivity)
        rise = _rise_check(raw_mentions[-window_points:], smooth_mentions[-window_points:], cfg)
        return TickerEvaluation(
            ticker=ticker,
            status="insufficient_history",
            days_collected=days_collected,
            days_needed=required_days,
            reasons=[f"Il manque {required_days - days_collected} jour(s) d'historique"],
            is_early_trend=(
                early["progressive"]
                and early["net_rise"] > 0
                and rise["enough_mentions"]
                and rise["big_enough"]
            ),
            mentions_series=mentions_history,
            price_series=price_history,
        )

    w = window_points
    baseline_slice = slice(-(w + cfg.baseline_days), -w)
    window_slice = slice(-w, None)

    window_mentions = smooth_mentions[window_slice]
    baseline_mentions = smooth_mentions[baseline_slice]
    mention_check = _is_progressive(window_mentions, baseline_mentions, cfg.anomaly_sensitivity)
    rise = _rise_check(raw_mentions[window_slice], window_mentions, cfg)

    reasons = []
    if not rise["enough_mentions"]:
        reasons.append(
            f"Trop peu de mentions (médiane {rise['median_mentions']:.1f}/jour, "
            f"minimum {cfg.min_median_mentions:g})"
        )
    if mention_check["net_rise"] <= 0:
        reasons.append("Pas de hausse nette des mentions sur la fenêtre")
    elif not rise["big_enough"]:
        reasons.append(
            f"Hausse trop faible (x{rise['rise_ratio']:.2f}, minimum x{cfg.min_rise_ratio:g})"
        )
    if not mention_check["progressive"]:
        day = mention_check["worst_day_offset"]
        reasons.append(
            f"Hausse concentrée sur un seul jour (z={mention_check['worst_z']:.1f}, "
            f"jour -{day} de la fenêtre)"
        )

    price_by_date = {p["date"]: p for p in price_history}
    all_dates = [m["date"] for m in mentions_history]
    baseline_dates = all_dates[baseline_slice]
    window_dates = all_dates[window_slice]
    if not all(d in price_by_date for d in baseline_dates + window_dates):
        return TickerEvaluation(
            ticker=ticker,
            status="insufficient_price_data",
            days_collected=days_collected,
            days_needed=required_days,
            reasons=["Historique de prix incomplet pour la période requise"],
            mentions_series=mentions_history,
            price_series=price_history,
        )

    baseline_prices = [price_by_date[d]["close"] for d in baseline_dates]
    baseline_volumes = [price_by_date[d]["volume"] for d in baseline_dates]
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

    # Progression dans le classement ApeWisdom : rang plus bas = meilleur, donc
    # on travaille sur -rang pour réutiliser le même détecteur "progressif" que
    # pour les mentions (pas de bond de classement en un seul jour).
    rank_check = _is_progressive(
        smooth_rank_scores[window_slice], smooth_rank_scores[baseline_slice], cfg.anomaly_sensitivity
    )

    if rank_check["net_rise"] <= 0:
        reasons.append("Le classement ApeWisdom ne progresse pas sur la fenêtre")
    if not rank_check["progressive"]:
        reasons.append(
            f"Progression de rang concentrée sur un seul jour (z={rank_check['worst_z']:.1f})"
        )

    # Qualité d'engagement : upvotes par mention. On ne pénalise qu'un
    # effondrement (mentions "creuses"), pas une hausse de qualité.
    def _engagement_ratio(m):
        return (m["upvotes"] / m["mentions"]) if m["mentions"] else 0.0

    baseline_engagement = [_engagement_ratio(m) for m in mentions_history[baseline_slice]]
    window_engagement = [_engagement_ratio(m) for m in mentions_history[window_slice]]
    engagement_check = _has_no_quality_collapse(
        window_engagement, baseline_engagement, cfg.engagement_sensitivity
    )

    if not engagement_check["ok"]:
        reasons.append(
            f"Qualité d'engagement en chute anormale, mentions possiblement creuses "
            f"(z={engagement_check['worst_z']:.1f})"
        )

    qualifies = (
        rise["enough_mentions"]
        and rise["big_enough"]
        and mention_check["net_rise"] > 0
        and mention_check["progressive"]
        and rank_check["net_rise"] > 0
        and rank_check["progressive"]
        and engagement_check["ok"]
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
        rank_start=mentions_history[-w]["rank"],
        rank_end=mentions_history[-1]["rank"],
        engagement_window_avg=statistics.mean(window_engagement) if window_engagement else None,
        engagement_baseline_avg=statistics.mean(baseline_engagement) if baseline_engagement else None,
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


def _has_no_quality_collapse(window_values, baseline_values, sensitivity):
    """Rejette seulement une chute anormale (mentions potentiellement creuses),
    jamais une hausse de qualité — contrairement à _is_stable qui est
    symétrique."""
    mean_v, std_v = _mean_std(baseline_values)
    z_scores = [(v - mean_v) / std_v for v in window_values]

    if not z_scores:
        return {"ok": True, "worst_z": 0.0}

    worst_z = min(z_scores)
    return {"ok": worst_z >= -sensitivity, "worst_z": worst_z}


def _pct_changes(values):
    changes = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev:
            changes.append((values[i] - prev) / prev)
        else:
            changes.append(0.0)
    return changes
