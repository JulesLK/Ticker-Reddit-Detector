# Screener Reddit — Intelligence Collective Progressive

Détecte les tickers dont l'intérêt Reddit augmente **progressivement**, sans
catalyseur identifiable (pas de news, pas de pic de prix), et écarte les
tickers dont l'attention est réactive (pic soudain lié à une actualité ou un
mouvement de prix déjà en cours).

C'est uniquement l'**Étage 1** : détection + filtrage → une liste de tickers.
L'analyse fondamentale (valorisation, décision d'achat) reste manuelle, hors
périmètre de cet outil.

## Comment ça marche

1. **Collecte quotidienne** : snapshot du classement [ApeWisdom](https://apewisdom.io)
   (mentions Reddit, rang, upvotes), stocké dans `data/reddit_mentions.db`
   (SQLite) pour reconstituer un historique jour par jour — l'API elle-même
   ne fournit pas d'historique long.
2. **Prix/volume** : récupérés via `yfinance` (Yahoo Finance). Les week-ends
   (marché fermé) sont rattachés au prix/volume de clôture du vendredi
   précédent.
3. **Détection** (par ticker, dès qu'il a assez d'historique) — 5 conditions :
   - hausse de mentions **progressive** : aucun jour ne doit représenter une
     part disproportionnée de la hausse (z-score du delta journalier par
     rapport à la baseline propre du ticker) ;
   - progression **progressive** dans le classement ApeWisdom (même logique
     appliquée au rang plutôt qu'au volume de mentions — capte un ticker qui
     gagne en importance relative, pas seulement en volume brut) ;
   - qualité d'engagement stable : le ratio upvotes/mentions ne doit pas
     s'effondrer par rapport à sa propre baseline (signe possible de
     mentions "creuses"/spam plutôt que d'une vraie conviction communautaire) ;
   - prix et volume restent dans une plage normale par rapport à la
     volatilité historique propre du ticker ;
   - un ticker qui casse une condition ou sort du classement ApeWisdom est
     simplement retiré de la liste du jour — pas de blacklist permanente, il
     peut revalider les critères plus tard.
4. **Dashboard** (`docs/index.html`, publié sur GitHub Pages) régénéré à
   chaque run : progression "Jour X / window_days", statut de la dernière
   collecte, nombre de tickers suivis, mini-courbes mentions + prix pour les
   tickers les plus actifs, mise en évidence des tendances naissantes, et
   rappel des paramètres utilisés pour produire les résultats affichés.

**Aucun signal n'est exploitable avant que la fenêtre glissante soit
complète (`window_days`, 14 jours par défaut).** Le dashboard existe pour
donner une preuve de vie quotidienne pendant cette accumulation.

## Configuration (`config.yaml`)

Tous les seuils sont dans ce fichier — rien n'est codé en dur dans la
logique. Modifier une valeur ne supprime jamais l'historique brut déjà
collecté : seul le recalcul du signal en tient compte. Si vous augmentez
`window_days` ou `baseline_days` après coup, l'outil indique qu'il manque des
jours d'historique plutôt que de produire un résultat basé sur une fenêtre
incomplète.

| Paramètre | Rôle |
|---|---|
| `window_days` | Taille de la fenêtre glissante d'analyse |
| `baseline_days` | Période de calcul de la normalité propre au ticker (doit être ≥ `window_days`) |
| `universe` | Filtre ApeWisdom scanné chaque jour |
| `max_pages` | Garde-fou sur la pagination ApeWisdom |
| `anomaly_sensitivity` | Seuil (en z-score) de hausse disproportionnée sur un seul jour, pour les mentions et pour le rang ApeWisdom |
| `price_volatility_sensitivity` | Seuil (en z-score) de mouvement de prix/volume anormal |
| `engagement_sensitivity` | Seuil (en z-score) de chute anormale du ratio upvotes/mentions |
| `run_time` | Heure UTC visée pour la collecte quotidienne |
| `early_trend_min_days` | Historique minimum pour signaler une "tendance naissante" avant fin de fenêtre |

## Exécution automatique

- **GitHub Actions** (`.github/workflows/daily-collect.yml`) tourne toutes
  les heures ; le script ne fait la vraie collecte que lorsque l'heure UTC
  correspond à `run_time` (± l'heure pile), ce qui évite d'avoir à modifier
  le cron à chaque changement de config. Un déclenchement manuel
  (`workflow_dispatch`) force toujours l'exécution, quelle que soit l'heure.
- Le workflow commit `data/reddit_mentions.db` et `docs/index.html` après
  chaque run, puis déploie `docs/` sur **GitHub Pages**.

### Activer GitHub Pages (une seule fois)

Dans les paramètres du repo → **Pages** → *Build and deployment* → **Source :
GitHub Actions**.

## Exécution locale

```bash
pip install -r requirements.txt
FORCE_RUN=1 python src/main.py
```

`FORCE_RUN=1` court-circuite la vérification d'heure pour lancer une collecte
immédiatement. Le dashboard généré est `docs/index.html`, ouvrable
directement dans un navigateur.

## Hors périmètre (versions futures)

- Score fondamental / valorisation (Étage 2), géré séparément par
  l'utilisateur.
- Détection de coordination/bots, analyse NLP du contenu des posts,
  croisement avec Google Trends / StockTwits.
- Intégration MCP.
