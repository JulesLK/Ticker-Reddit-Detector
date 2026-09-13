"""Client pour l'API publique ApeWisdom (https://apewisdom.io), gratuite et
sans clé. Fournit les mentions Reddit du jour par ticker, mais pas
d'historique long — c'est storage.py qui reconstitue l'historique via des
snapshots quotidiens."""

from datetime import datetime, timezone
import time
import requests

BASE_URL = "https://apewisdom.io/api/v1.0/filter/{filter}/page/{page}"
TIMEOUT = 20
RETRY_DELAY_SECONDS = 3
MAX_RETRIES = 3


def _fetch_page(filter_name: str, page: int) -> dict:
    url = BASE_URL.format(filter=filter_name, page=page)
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Échec de récupération ApeWisdom page {page}: {last_exc}")


def fetch_universe(filter_name: str, max_pages: int):
    """Récupère tout le classement ApeWisdom pour le filtre donné, jusqu'à
    max_pages. Retourne une liste de dicts normalisés prêts pour storage.py."""

    first = _fetch_page(filter_name, 1)
    total_pages = min(int(first.get("pages", 1)), max_pages)
    all_results = list(first.get("results", []))

    for page in range(2, total_pages + 1):
        data = _fetch_page(filter_name, page)
        all_results.extend(data.get("results", []))

    normalized = []
    for r in all_results:
        try:
            normalized.append(
                {
                    "ticker": r["ticker"].strip().upper(),
                    "mentions": int(r.get("mentions", 0)),
                    "mentions_24h_ago": int(r.get("mentions_24h_ago", 0)),
                    "rank": int(r.get("rank", 0)),
                    "upvotes": int(r.get("upvotes", 0)),
                }
            )
        except (KeyError, ValueError, TypeError):
            continue

    return normalized


def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
