# First Basket Match

NBA first-basket Streamlit research app. Free ESPN data; no API key. Version 1.5.

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

While the page is open, the main view refreshes every 60 seconds. Starter summaries use a 45-second cache, the scoreboard/roster a five-minute cache, history a 30-minute cache, and final raw summaries a one-day cache. The Refresh data button clears caches immediately. Closed pages do not run lineup refreshes. A separate GitHub Actions archive job can capture default-setting records while the page is closed, as described below.

## Slate shortlist

Load all desired matchups. The shortlist selects up to four candidates from different games by highest model game-first estimate. Both teams must have source-confirmed lineups and future scheduled tip times. Both need at least five sampled games; the player needs three starts, three early shot attempts, one team opening-shot attempt, and one team-first scoring hit. These are initial research rules, not validated profitability thresholds. Fewer than four picks may qualify. Team filters do not change this selection.

Current sportsbook odds can be entered manually in the optional section. There is no odds feed, prices do not change the selections, and no freshness guarantee is made. Missing or invalid prices stay blank.

## Model and results

Game first and team first are separate estimates. Field-goal settlement excludes free throws; first-points settlement includes them. Match your sportsbook's rules.

The model combines smoothed first-scoring history (60%) and opening-shot share times early conversion (40%). Bounded position adjustments distinguish first-shot attempts allowed from first made field goals allowed. Tip estimates are team-history context only, not confirmed individual-jumper probabilities. G/F/C groups are used without inventing detailed positions. Missing or small position samples are neutral. Unlisted-player probability is retained. See How it works for the full formula and limitations.

Green marks the top eligible candidate in a game only when both lineups are source-confirmed, each team has at least 15 sampled games, and the player has eight starts. Amber marks limited history; gray marks awaiting starters; other rows stay navy. The same rules and readable white text apply to both the shortlist and full board. Color labels remain visible and do not change estimates, ranks or selection rules. Colors and ranks are not proven betting edges.

## Automatic pregame records

The app automatically keeps the latest pretip forecast for each loaded game and settlement basis in the open session. These records include your current settings, shortlist flags and manually entered prices. Session records are temporary and can disappear on disconnect; downloading your own copy remains useful.

A separate GitHub Actions workflow runs approximately every ten minutes, subject to GitHub scheduling delays and repository permissions. It captures games within two hours before scheduled tip, using up to 20 current-season regular-season games and field-goal settlement. It does not copy private user inputs or manually entered sportsbook prices. Only public model data is committed under `data/pregame/`. Projections are labeled; only source-confirmed candidates can be shortlisted. Capture failures are reported, not backfilled with postgame rankings. A source that publishes starters after tip cannot produce a confirmed pregame shortlist record.

The archive keeps the latest captured pretip board per game; after tip its forecast rows remain unchanged. Final results are appended separately with a hash of the original forecast rows. Results tracker reads the latest repository records automatically and can also settle open-session records when final data becomes available. Its automatic archive scope differs from a user-selected slate; overall ranks refer to that record's capture scope. Missing captures, scheduling delays, public-feed outages and unavailable lineups remain possible. GitHub Actions must be enabled and allowed to write repository contents. The workflow supports a manual Run workflow action too.

Earlier version 1.0–1.4 snapshots remain supported through optional upload. No historical win rate, ROI or profitability is claimed.

## Added research context

Opening-matchup details show actual first-FG and first-points conversions **after identified tip wins**, with their true denominators. Historical jumper counts are shown without claiming today's jumper or head-to-head odds. Opening shot styles distinguish layups, dunks, hooks, 2PT jumpers and 3PT shots; unknown types are excluded. Ties show no clear position or style preference. These new context statistics do not alter the forecast weights; prospective results are needed to evaluate them.

A second NBA.com feed was inaccessible from the build environment. No unverified backup starter integration is claimed; ESPN remains the current lineup source.

## Checks

```bash
python -m unittest -v
```

Coverage includes free-throw vs field-goal parsing, chronological events, exact pregame source-lineup validation, probability mass, directional position allowances, missing data, minimum samples, distinct-game shortlist selection, source-pending/source-confirmed UI behavior, manual prices and settlement-basis switching.
