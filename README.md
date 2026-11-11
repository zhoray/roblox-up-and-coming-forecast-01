# Next In Line — Roblox Up-and-Coming forecaster

Entry for make.fun's **roblox-up-and-coming-forecast-01**: a program that
reads the history of Roblox's Up-and-Coming chart (device computer,
country US) and writes one forecast — a probability for each game at each
of the top 10 places, plus a top-10 guess — for the 72 hours after entries
close, scored by log score against the house recorder's hourly reads.

## Run it

```
mkdir -p out
MAKEFUN_INPUT_DIR=<dir with task.json + history.ndjson> \
MAKEFUN_OUTPUT_DIR=out \
python3 main.py
```

In the grader's container both variables are unset and it reads `/input`
and writes `/output/forecast.json`. Python 3.13, standard library only,
no network. Two runs on the same history write the same bytes.

## Method

Each game gets a latent chart strength `s = -ln(rank)`:

- **Level**: exponentially weighted mean of `s` over its rank track
  (12 h half-life; reads where the game is off the chart are imputed just
  below the chart's foot, so a vanished game fades instead of freezing at
  its last rank).
- **Drift**: a shrunk, capped per-hour slope of `s` over the last 5 days.
- **Noise**: the per-hour random-walk sigma of `s`, fitted from the
  history's own consecutive reads (scaled ×1.2).
- **Newcomers**: a Poisson stream of phantom games whose entry strengths
  are drawn from the history's first-appearance distribution, with a
  positive drift bias — the chart's top 10 is regularly taken by games
  nobody could name yet.
- **Ageing out**: when the history carries Roblox's per-game details, a
  game leaves the simulated chart once it is 28 days old, as the real
  chart drops it.

A seeded Monte Carlo (1,200 simulations × the window's hours) walks every
candidate strength forward and records who holds each place; occupancy,
averaged over hours, is flattened (exponent 0.5) into each place's named
probability mass. Every place keeps an unnamed share at least as large as
its phantom share, which is what the scorer spreads over the games the
forecast does not name.

## Validation

The kit's scorer is sealed, so the score was replicated exactly from the
published rules and checked against the house baseline's known practice
figures (replica: −43.512039, 6.4 hits, 53.5 agreement — matching). On
the practice instance (history to 2026-11-07T23:00Z, scored on the public
archive's 10 reads in the practice window) this program scores
**−36.34**, against the house persistence baseline's −43.51. Across five
rolling origins in the archive it beat the baseline every time
(mean −41.08 vs −48.27).

## License

MIT — see `LICENSE`.
