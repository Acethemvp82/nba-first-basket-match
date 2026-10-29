# Validation — October 23, 2026

## Version 1.4 — October 29, 2026

Removed manual starter selection/confirmation and added exact-event ESPN starter flag validation with clear projected fallback. Main UI refreshes while open via Streamlit fragments every 60 seconds; current starter summaries cache for 45 seconds. Sixteen checks passed, including automatic transition between pending and source-confirmed lineups, absence of manual verification controls, rejection of old-game/postgame/incomplete/non-roster starters and exclusion from the shortlist when confirmation disappears. Live ESPN pregame summaries were reachable but had no starter records at test time; no confirmed live pregame lineup was falsely claimed or inferred. No specific pre-tip publication time is guaranteed.

## Version 1.3 — October 29, 2026

Added a distinct-game shortlist with transparent minimum samples, user-confirmed lineups, pregame eligibility, manually entered prices, and snapshot tracking flags. Tests verify ranking and four-game cap, exclusion of insufficient history and started games, no forced filler picks, and UI behavior for confirmations, blank/entered odds, and changed lineups. Forecast weights and probabilities are unchanged by the shortlist feature. This validation does not establish betting accuracy or profitability.

## Version 1.2 upgrade

Thirteen model and Streamlit checks passed. New coverage separates free throws, missed opening attempts, and the first made field goal; verifies directional opponent position counts and observed percentages; checks minimum samples and unknown-position neutrality; preserves game probability mass after both position adjustments; and verifies per-player explanations in the rendered board. A real historical summary also parsed both teams' first made field goals and usable allowance profiles. This is implementation validation, not evidence of increased betting accuracy.

- Eight automated checks passed, including a Streamlit app test that renders ten players and switches settlement basis.
- Live ESPN scoreboard, team schedule, roster and game summary requests succeeded from the build environment.
- A completed October 22, 2025 game parsed both field-goal and first-points outcomes, five historical starters for each team, and opening shooting data.
- A live pregame matchup loaded ten ranked players with the previous-season option enabled and five requested games per team. The app reported no errors in that run. Default current-season-only mode withheld the tested matchup when there was insufficient completed history.
- Fixed a fractional-clock parsing issue discovered in real play-by-play.
- Probability checks retain unlisted-player mass and enforce a total of one per game. Target games and later games are excluded from historical selection.

Verification used Streamlit's AppTest, not a visual browser inspection. No betting backtest, calibration, profit study or Streamlit deployment was completed. This is an experimental research model. A current feed request succeeding does not guarantee future availability.

## Version 1.1 upgrade

Added first-shot position profiles from historical lineups, directional opponent allowance, bounded shot-component adjustment, and explicitly identified opening-tip context. Added tests for ambiguous or later jump balls, missing positions, opponent direction, minimum samples, complementary tip estimates, and probability conservation with adjustment. Eleven model/UI checks passed. Live historical PBP identified an opening tip recipient successfully. Tip estimates do not affect scoring probabilities. No improvement in betting accuracy is claimed.

## Version 1.5 — October 29, 2026

Twenty-one checks passed, covering tip-conversion denominators, field-goal vs first-points separation, unknown shot types and tied summaries, historical jumpers, session autosave, refusing after-tip/older forecast replacement, preserving original rows during settlement, and a full background capture-to-settlement simulation. The real ESPN historical fixture parsed both jumpers and the opening-tip recipient. A real archive run completed successfully with no eligible games inside its two-hour capture window and no source errors. The NBA.com backup feed returned HTTP 403; no second-source success is claimed. New research context does not change forecast weights. Live GitHub scheduler operation must be checked separately after publication.
