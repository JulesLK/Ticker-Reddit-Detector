"""Génère le dashboard HTML statique (docs/index.html, servi par GitHub
Pages). Page autonome : pas de dépendance JS/CSS externe, régénérée à chaque
run pour donner une preuve de vie quotidienne pendant la période d'accumulation
(aucun signal n'est exploitable avant que window_days soit atteint)."""

from datetime import datetime, timezone
import html


def _normalize(values):
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _sparkline_svg(mentions_series, price_series, width=260, height=70):
    if len(mentions_series) < 2:
        return '<svg width="{}" height="{}"></svg>'.format(width, height)

    mentions = [m["mentions"] for m in mentions_series]
    dates = {p["date"]: p["close"] for p in price_series}
    prices = [dates.get(m["date"]) for m in mentions_series]
    has_price = all(p is not None for p in prices)

    norm_mentions = _normalize(mentions)
    n = len(norm_mentions)
    pad = 6
    step = (width - 2 * pad) / (n - 1)

    def to_points(norm_values):
        pts = []
        for i, v in enumerate(norm_values):
            x = pad + i * step
            y = height - pad - v * (height - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    mentions_points = to_points(norm_mentions)
    svg = [f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}">']
    svg.append(
        f'<polyline points="{mentions_points}" fill="none" stroke="var(--mentions-color)" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />'
    )

    if has_price and len(set(prices)) > 1:
        norm_prices = _normalize(prices)
        price_points = to_points(norm_prices)
        svg.append(
            f'<polyline points="{price_points}" fill="none" stroke="var(--price-color)" '
            f'stroke-width="1.5" stroke-dasharray="3,3" opacity="0.75" />'
        )

    svg.append("</svg>")
    return "".join(svg)


def _logo_url(ticker):
    safe = "".join(c for c in ticker if c.isalnum())
    return f"https://financialmodelingprep.com/image-stock/{safe}.png"


def _rank_html(evaluation):
    if evaluation.rank_start is None or evaluation.rank_end is None:
        return ""
    arrow = "▲" if evaluation.rank_end < evaluation.rank_start else "▼" if evaluation.rank_end > evaluation.rank_start else "→"
    return f'<div class="meta-line">Rang ApeWisdom : #{evaluation.rank_start} {arrow} #{evaluation.rank_end}</div>'


def _engagement_html(evaluation):
    if evaluation.engagement_window_avg is None or evaluation.engagement_baseline_avg is None:
        return ""
    return (
        f'<div class="meta-line">Engagement (upvotes/mention) : '
        f'{evaluation.engagement_window_avg:.1f} (baseline {evaluation.engagement_baseline_avg:.1f})</div>'
    )


def _card(ticker, evaluation, highlight_class=""):
    reasons_html = ""
    if evaluation.reasons:
        items = "".join(f"<li>{html.escape(r)}</li>" for r in evaluation.reasons)
        reasons_html = f'<ul class="reasons">{items}</ul>'

    spark = _sparkline_svg(evaluation.mentions_series, evaluation.price_series)
    last_mentions = evaluation.mentions_series[-1]["mentions"] if evaluation.mentions_series else "-"
    logo_url = _logo_url(ticker)

    return f"""
    <div class="card {highlight_class}">
        <div class="card-header">
            <span class="ticker-group">
                <img class="logo" src="{logo_url}" alt="" loading="lazy" onerror="this.style.display='none'" />
                <span class="ticker">{html.escape(ticker)}</span>
            </span>
            <span class="mentions-count">{last_mentions} mentions</span>
        </div>
        <div class="sparkline">{spark}</div>
        {_rank_html(evaluation)}
        {_engagement_html(evaluation)}
        {reasons_html}
    </div>
    """


def render_dashboard(cfg, last_collection, days_collected_global, tracked_count, evaluations):
    """evaluations: dict[ticker] -> TickerEvaluation"""

    qualifying = {t: e for t, e in evaluations.items() if e.status == "qualifies"}
    early_trend = {t: e for t, e in evaluations.items() if e.is_early_trend}
    most_active = sorted(
        evaluations.items(),
        key=lambda kv: kv[1].mentions_series[-1]["mentions"] if kv[1].mentions_series else 0,
        reverse=True,
    )[:12]

    progress_pct = min(100, round(100 * days_collected_global / cfg.window_days))

    if last_collection:
        status = last_collection["status"]
        ts = last_collection["timestamp"]
        msg = last_collection.get("message") or ""
        status_class = "status-ok" if status == "success" else "status-error"
    else:
        status, ts, msg, status_class = "aucune collecte pour l'instant", "-", "", "status-error"

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    qualifying_html = (
        "".join(_card(t, e, "highlight-qualify") for t, e in qualifying.items())
        if qualifying
        else '<p class="empty">Aucun ticker ne valide toutes les conditions aujourd\'hui.</p>'
    )
    early_trend_html = (
        "".join(_card(t, e, "highlight-early") for t, e in early_trend.items())
        if early_trend
        else '<p class="empty">Aucune tendance naissante détectée pour l\'instant.</p>'
    )
    most_active_html = "".join(_card(t, e) for t, e in most_active)

    return f"""<!doctype html>
<html lang="fr" data-theme="dark">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Screener Reddit — Intelligence Collective Progressive</title>
<style>
  :root {{
    --bg: #0b0d12;
    --panel: #141822;
    --border: #262c3a;
    --text: #e6e9f0;
    --muted: #8993a8;
    --accent: #5b8cff;
    --good: #3ecf8e;
    --warn: #e8b94b;
    --bad: #e8576b;
    --mentions-color: #5b8cff;
    --price-color: #e8b94b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, Segoe UI, Roboto, sans-serif;
    margin: 0;
    padding: 24px 32px 64px;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 24px; }}
  .top-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .stat-box {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }}
  .stat-label {{ color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat-value {{ font-size: 1.6rem; font-weight: 600; margin-top: 4px; }}
  .progress-bar-track {{
    background: var(--border);
    border-radius: 6px;
    height: 10px;
    margin-top: 10px;
    overflow: hidden;
  }}
  .progress-bar-fill {{
    background: var(--accent);
    height: 100%;
  }}
  .status-ok {{ color: var(--good); }}
  .status-error {{ color: var(--bad); }}
  section {{ margin-bottom: 36px; }}
  section h2 {{ font-size: 1.05rem; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
    margin-top: 14px;
  }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
  }}
  .card.highlight-qualify {{ border-color: var(--good); box-shadow: 0 0 0 1px var(--good) inset; }}
  .card.highlight-early {{ border-color: var(--warn); box-shadow: 0 0 0 1px var(--warn) inset; }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
  .ticker-group {{ display: flex; align-items: center; gap: 8px; }}
  .logo {{ width: 22px; height: 22px; border-radius: 5px; object-fit: contain; background: #fff1; }}
  .ticker {{ font-weight: 700; font-size: 1.05rem; }}
  .mentions-count {{ color: var(--muted); font-size: 0.8rem; }}
  .sparkline svg {{ display: block; width: 100%; height: auto; }}
  .meta-line {{ color: var(--muted); font-size: 0.75rem; margin-top: 4px; }}
  .reasons {{ margin: 8px 0 0; padding-left: 18px; color: var(--muted); font-size: 0.78rem; }}
  .empty {{ color: var(--muted); font-size: 0.9rem; }}
  .config-box {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
    font-size: 0.82rem;
    color: var(--muted);
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 6px 20px;
  }}
  .config-box b {{ color: var(--text); }}
  footer {{ color: var(--muted); font-size: 0.75rem; margin-top: 40px; }}
</style>
</head>
<body>
  <h1>Screener Reddit — Intelligence Collective Progressive</h1>
  <div class="subtitle">Dashboard régénéré automatiquement à chaque collecte · dernière génération : {generated_at}</div>

  <div class="top-grid">
    <div class="stat-box">
      <div class="stat-label">Progression de la fenêtre</div>
      <div class="stat-value">Jour {min(days_collected_global, cfg.window_days)} / {cfg.window_days}</div>
      <div class="progress-bar-track"><div class="progress-bar-fill" style="width:{progress_pct}%"></div></div>
    </div>
    <div class="stat-box">
      <div class="stat-label">Dernière collecte</div>
      <div class="stat-value {status_class}">{html.escape(str(status))}</div>
      <div class="subtitle" style="margin:4px 0 0;">{html.escape(str(ts))}{(' — ' + html.escape(msg)) if msg else ''}</div>
    </div>
    <div class="stat-box">
      <div class="stat-label">Tickers suivis actuellement</div>
      <div class="stat-value">{tracked_count}</div>
    </div>
    <div class="stat-box">
      <div class="stat-label">Signaux validés aujourd'hui</div>
      <div class="stat-value">{len(qualifying)}</div>
    </div>
  </div>

  <section>
    <h2>Paramètres utilisés pour ces résultats</h2>
    <div class="config-box">
      <div>window_days : <b>{cfg.window_days}</b></div>
      <div>baseline_days : <b>{cfg.baseline_days}</b></div>
      <div>universe : <b>{html.escape(cfg.universe)}</b></div>
      <div>anomaly_sensitivity : <b>{cfg.anomaly_sensitivity}</b></div>
      <div>price_volatility_sensitivity : <b>{cfg.price_volatility_sensitivity}</b></div>
      <div>engagement_sensitivity : <b>{cfg.engagement_sensitivity}</b></div>
      <div>run_time (UTC) : <b>{html.escape(cfg.run_time)}</b></div>
    </div>
  </section>

  <section>
    <h2>Signaux validés</h2>
    <p class="subtitle" style="margin-top:-6px;">
      Mentions en hausse progressive · classement ApeWisdom qui grimpe progressivement ·
      engagement (upvotes/mention) sain · prix et volume stables.
    </p>
    <div class="grid">{qualifying_html}</div>
  </section>

  <section>
    <h2>Tendances naissantes (avant fin de fenêtre)</h2>
    <div class="grid">{early_trend_html}</div>
  </section>

  <section>
    <h2>Tickers les plus actifs (toutes conditions confondues)</h2>
    <div class="grid">{most_active_html}</div>
  </section>

  <footer>Sources : ApeWisdom (mentions Reddit) · Yahoo Finance via yfinance (prix/volume). Étage 1 uniquement — pas d'analyse fondamentale.</footer>
</body>
</html>
"""
