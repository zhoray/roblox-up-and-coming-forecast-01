# Roblox Up-and-Coming forecast

main.py reads the task configuration and chart snapshots from
MAKEFUN_INPUT_DIR (default /input) and writes the requested forecast under
MAKEFUN_OUTPUT_DIR (default /output).

For each game, the model combines an exponentially decreasing rank signal
with a modest playing-count cue. It updates a normalized exponentially
weighted average using the actual elapsed time between reads. The 1.5-hour
half-life makes the estimate responsive to recent chart movement while
handling irregular snapshot spacing explicitly. Missing games receive no
observation on that read.

The forecast runs seeded Monte Carlo paths over the requested number of hourly
slots. Latent strengths are standardized, then each game's strength mean
reverts toward its recent estimate (0.25 per step) with Gaussian hourly noise
(standard deviation 0.17). Each simulated hour contributes its top-place
assignments to frequency estimates, with earlier forecast hours weighted
somewhat more (36-hour exponential weighting). A small pseudocount smooths the
listed probabilities, and 15% of each place's mass remains unnamed to cover
unseen outcomes. Only games observed in the history are named. The top10 list
ranks games by accumulated chance of occupying any forecast top-ten place,
then by their expected place.

The implementation uses only the Python standard library and produces
deterministic JSON for a fixed input.
