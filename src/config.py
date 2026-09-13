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
    )

    if cfg.baseline_days < cfg.window_days:
        raise ValueError(
            "baseline_days doit être >= window_days pour que la baseline "
            "reste plus large que la fenêtre d'analyse."
        )

    return cfg
