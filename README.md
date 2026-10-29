# First Basket Match

NBA first-basket Streamlit research app. Free ESPN data; no API key. Version 1.4.

## Run and deploy

Use Python 3.11 or 3.12:

```bash
pip install -r requirements.txt
streamlit run app.py
```

Streamlit Community Cloud: repository `Acethemvp82/nba-first-basket-match`, branch `main`, main file `app.py`. The app is independent of ESPN and the NBA. Public endpoints may change or be unavailable.

## Starting lineups: automatic

No manual starter selection or verification is required. For each loaded matchup, the app reads the ESPN current-game summary. It accepts exactly five explicit starter flags per team only when the event ID, tip timestamp, and pregame state match the selected game; all five distinct IDs must belong to the current roster and none may be marked did-not-play.

The app shows **Source confirmed — ESPN game feed** when those checks pass. Otherwise it shows **Projected — awaiting source confirmation**, using the latest sampled game's starters intersected with the current roster for the research board. Projections never count as confirmed and cannot enter the shortlist. If fewer than five projected players remain, that matchup is withheld. Feed failures are disclosed. There is no promise that ESPN publishes starter records before tip, and starter flags are not an independent injury model.

While the page is open, the main view refreshes every 60 seconds. Starter summaries use a 45-second cache, the scoreboard/roster a five-minute cache, history a 30-minute cache, and final raw summaries a one-day cache. The Refresh data button clears caches immediately. Closed pages do not update in the background.

## Slate shortlist

Load all desired matchups. The shortlist selects up to four candidates from different games by highest model game-first estimate. Both teams must have source-confirmed lineups and future scheduled tip times. Both need at least five sampled games; the player needs three starts, three early shot attempts, one team opening-shot attempt, and one team-first scoring hit. These are initial research rules, not validated profitability thresholds. Fewer than four picks may qualify. Team filters do not change this selection.

Current sportsbook odds can be entered manually in the optional section. There is no odds feed, prices do not change the selections, and no freshness guarantee is made. Missing or invalid prices stay blank.

## Model and results

Game first and team first are separate estimates. Field-goal settlement excludes free throws; first-points settlement includes them. Match your sportsbook's rules.

The model combines smoothed first-scoring history (60%) and opening-shot share times early conversion (40%). Bounded position adjustments distinguish first-shot attempts allowed from first made field goals allowed. Tip estimates are team-history context only, not confirmed individual-jumper probabilities. G/F/C groups are used without inventing detailed positions. Missing or small position samples are neutral. Unlisted-player probability is retained. See How it works for the full formula and limitations.

Green means a top-two team research candidate with at least 15 sampled games and eight player starts; amber means limited history. Colors and ranks are not proven betting edges.

Download a pregame JSON snapshot before tip. It preserves lineup status, source check time, ranks, shortlist flags and entered odds. Upload it to Results tracker after games finish to settle the saved board, including shortlist hits and pending games. Keep the file on your device: storage is not automatic or audited. Earlier 1.0–1.3 snapshots remain supported. No historical win rate, ROI or profitability is claimed.

## Checks

```bash
python -m unittest -v
```

Coverage includes free-throw vs field-goal parsing, chronological events, exact pregame source-lineup validation, probability mass, directional position allowances, missing data, minimum samples, distinct-game shortlist selection, source-pending/source-confirmed UI behavior, manual prices and settlement-basis switching.
