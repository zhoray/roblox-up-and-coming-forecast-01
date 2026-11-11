# Roblox Up-and-Coming Forecast

The forecaster models each game's latent chart strength as negative log rank. A 4-hour EWMA estimates its level. A shrunk, time-weighted regression estimates long-horizon drift, while a separate regression over the last 48 hours estimates short-window velocity. Velocity is shrunk by the observation count, clamped to ±0.10 per hour, and fades as exp(-h/30) in the forecast. Each game's strength also reverts toward its best observed strength in the last 96 hours at a rate of 0.01 per hour.

Hourly strength changes combine the fitted read-to-read diffusion, widened by 1.12, with Student-t noise. The simulation includes per-path breakout jumps for games outside the top 10 at the start: probabilities are 0.10 for ranks 11–20, 0.07 for 21–35, 0.055 for 36–60, and 0.04 for rank 61 and below. Jump sizes are Normal(1.7, 0.55), clipped to [0.6, 3.2], and phase in over 18 hours. New arrivals come from a Poisson stream fitted to historical first appearances and strengths. Games with known creation times age out after 28 days.

Across 1,500 simulations with a fixed seed, each forecast hour contributes equally to place occupancy. Output probabilities receive temperature-0.85 calibration, with at least 15% of each place's mass reserved for unnamed games (or more when simulated entrants take a larger share). The program reads settings from task.json and accepts MAKEFUN_INPUT_DIR and MAKEFUN_OUTPUT_DIR for its input and output directories.

Measured performance: official practice log score -35.67, versus -43.51 for the persistence baseline; 5-origin rolling backtest mean -39.51.

Run with python3 main.py.
