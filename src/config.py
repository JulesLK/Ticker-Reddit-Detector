"""Chargement de config.yaml. Aucun paramètre de détection ne doit être
codé en dur ailleurs dans le projet — tout passe par cet objet."""

from dataclasses import dataclass
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"
DB_PATH = REPO_ROOT / "data" / "reddit_mentions.db"
DASHBOARD_PATH = REPO_ROOT / "docs" / "index.html"


@dataclass(frozen=True)
class Config:
    window_days: int
    baseline_days: int
    universe: str
    max_pages: int
    anomaly_sensitivity: float
    price_volatility_sensitivity: float
    engagement_sensitivity: float
    run_time: str
    early_trend_min_days: int
    smoothing_days: int = 7
    min_median_mentions: float = 5
    min_rise_ratio: float = 1.5
    excluded_tickers: tuple = ()
    benchmark: str = "SPY"
    signal_horizons: tuple = (5, 10, 20)
    success_win_rate: float = 0.55
    success_min_signals: int = 30

    @property
    def run_time_hour_utc(self) -> int:
        return int(self.run_time.split(":")[0])


def load_config(path: Path = CONFIG_PATH) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cfg = Config(
        window_days=int(raw["window_days"]),
        baseline_days=int(raw["baseline_days"]),
        universe=str(raw["universe"]),
        max_pages=int(raw["max_pages"]),
        anomaly_sensitivity=float(raw["anomaly_sensitivity"]),
        price_volatility_sensitivity=float(raw["price_volatility_sensitivity"]),
        engagement_sensitivity=float(raw["engagement_sensitivity"]),
        run_time=str(raw["run_time"]),
        early_trend_min_days=int(raw["early_trend_min_days"]),
        smoothing_days=int(raw.get("smoothing_days", 7)),
        min_median_mentions=float(raw.get("min_median_mentions", 5)),
        min_rise_ratio=float(raw.get("min_rise_ratio", 1.5)),
        excluded_tickers=tuple(str(t).strip().upper() for t in raw.get("excluded_tickers") or ()),
        benchmark=str(raw.get("benchmark", "SPY")).upper(),
        signal_horizons=tuple(int(h) for h in raw.get("signal_horizons", (5, 10, 20))),
        success_win_rate=float(raw.get("success_win_rate", 0.55)),
        success_min_signals=int(raw.get("success_min_signals", 30)),
    )

    if cfg.baseline_days < cfg.window_days:
        raise ValueError(
            "baseline_days doit être >= window_days pour que la baseline "
            "reste plus large que la fenêtre d'analyse."
        )

    return cfg
