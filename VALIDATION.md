# Validation — October 23, 2026

- Eight automated checks passed, including a Streamlit app test that renders ten players and switches settlement basis.
- Live ESPN scoreboard, team schedule, roster and game summary requests succeeded from the build environment.
- A completed October 22, 2025 game parsed both field-goal and first-points outcomes, five historical starters for each team, and opening shooting data.
- A live pregame matchup loaded ten ranked players with the previous-season option enabled and five requested games per team. The app reported no errors in that run. Default current-season-only mode withheld the tested matchup when there was insufficient completed history.
- Fixed a fractional-clock parsing issue discovered in real play-by-play.
- Probability checks retain unlisted-player mass and enforce a total of one per game. Target games and later games are excluded from historical selection.

Verification used Streamlit's AppTest, not a visual browser inspection. No betting backtest, calibration, profit study or Streamlit deployment was completed. This is an experimental research model. A current feed request succeeding does not guarantee future availability.

## Version 1.1 upgrade

Added first-shot position profiles from historical lineups, directional opponent allowance, bounded shot-component adjustment, and explicitly identified opening-tip context. Added tests for ambiguous or later jump balls, missing positions, opponent direction, minimum samples, complementary tip estimates, and probability conservation with adjustment. Eleven model/UI checks passed. Live historical PBP identified an opening tip recipient successfully. Tip estimates do not affect scoring probabilities. No improvement in betting accuracy is claimed.
