"""Récupération prix/volume via yfinance. Le marché est fermé le week-end
(et les jours fériés) : ces jours-là on rattache le prix/volume de clôture du
dernier jour de bourse précédent, pour que le calcul de stabilité prix/volume
reste défini tous les jours où l'on a une mention Reddit."""

from datetime import datetime, timedelta
import yfinance as yf


def fetch_price_history(tickers, start_date: str, end_date: str):
    """Retourne {ticker: {date_str: {"close": float, "volume": int}}} pour les
    jours de bourse réels dans [start_date, end_date] (bornes incluses)."""

    if not tickers:
        return {}

    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    result = {t: {} for t in tickers}
    try:
        data = yf.download(
            tickers=list(tickers),
            start=start_date,
            end=end_dt.strftime("%Y-%m-%d"),
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )
    except Exception:
        return result

    single_ticker = len(tickers) == 1

    for t in tickers:
        try:
            df = data if single_ticker else data[t]
        except (KeyError, TypeError):
            continue
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["Close"])
        for idx, row in df.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            try:
                result[t][date_str] = {
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                }
            except (ValueError, TypeError):
                continue

    return result


def build_daily_series_with_carry(trading_days: dict, start_date: str, end_date: str):
    """trading_days: {date_str: {"close":.., "volume":..}} pour un seul ticker,
    jours de bourse réels uniquement. Retourne une liste de dicts couvrant
    CHAQUE jour calendaire entre start_date et end_date, en reportant le
    dernier close/volume connu sur les jours sans donnée de marché (week-ends
    et jours fériés), avec is_weekend_carry=1 sur ces jours-là."""

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    series = []
    last_close, last_volume = None, None
    day = start_dt
    while day <= end_dt:
        date_str = day.strftime("%Y-%m-%d")
        if date_str in trading_days:
            last_close = trading_days[date_str]["close"]
            last_volume = trading_days[date_str]["volume"]
            series.append(
                {"date": date_str, "close": last_close, "volume": last_volume, "is_weekend_carry": 0}
            )
        elif last_close is not None:
            series.append(
                {"date": date_str, "close": last_close, "volume": last_volume, "is_weekend_carry": 1}
            )
        # si aucune donnée n'existe encore (avant le premier jour de bourse
        # disponible), on n'ajoute rien plutôt que d'inventer un prix.
        day += timedelta(days=1)

    return series
