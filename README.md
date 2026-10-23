# First Basket Match

Separate NBA first-basket Streamlit research app. Uses free ESPN data; no API key.

## Run

Use Python 3.11 or 3.12:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

Create a new GitHub repository named `nba-first-basket-match`, upload **app.py**, **model.py**, **requirements.txt**, and optionally `.streamlit/config.toml`. On https://share.streamlit.io create an app from that repository, choose `app.py` as the main file and Python 3.11 or 3.12, then deploy. This package does not modify your NBA prop model.

## Use

1. Choose the Eastern slate date and settlement basis. Field goal excludes free throws; First points includes them. Check your book's settlement rules.
2. Select games and click Load / update prediction board. Schedule appears first.
3. Review the latest sampled starters against today's roster. Select five on each team, check availability, and confirm them yourself. Defaults are projections, not verified starting lineups.
4. Read team and overall ranks. Amber indicates limited data. Green is a relative team candidate with at least 15 sampled games and 8 starts, not a validated bet tier.
5. Enter a sportsbook price for a model-versus-price comparison. The model has not been calibrated; displayed positive EV is not proof of value.
6. Download a JSON snapshot before tip. Upload it to Results tracker after final to settle it. Snapshots live on your device and must be kept; nothing claims permanent disk tracking or background refresh.

The default uses up to 20 current regular-season games before target tip. The optional previous-season switch increases the available sample but can import stale player roles. No preseason/playoffs. Missing opening PBP is skipped and disclosed. Matchups with missing team history or current roster are withheld. Manual refresh clears cache; ordinary reruns reuse it.

Ten listed players do not sum to 100%; residual probability is reserved for other players. Team-first estimates use a 60% smoothed first-scoring share and 40% normalized opening-attempt share times smoothed early conversion. Team matchup estimates shrink historical game-first rates toward 50%. All coefficients are explicit heuristics, not trained parameters. See the app's How it works tab.

Not included: automated confirmed starters, injury adjustment, tip-off matchup model, sportsbook price feeds, proven hit rates, audited tracking or automatic Streamlit hosting. The full roster filter comes from ESPN and may use generic G/F positions.

## Check

```bash
python -m unittest -v
```

Tests cover first-points vs field-goal parsing, event ordering, missing data, probability conservation including bench residual, valid lineups, strict pregame cutoff and odds conversion. Live connectivity varies by hosting provider; ESPN public endpoints are unofficial and may change.

Data: https://www.espn.com/nba/ ; API root https://site.api.espn.com/apis/site/v2/sports/basketball/nba/ . This independent app is not affiliated with ESPN or the NBA.
