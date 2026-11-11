#!/usr/bin/env python3
"""Forecast the Roblox Up-and-Coming chart from its recent history."""

import datetime as dt
import json
import math
import os
import random
from pathlib import Path

SEED = 1729
SIMULATIONS = 900
HALF_LIFE_HOURS = 1.5
MAX_ROWS_PER_PLACE = 100


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_inputs(input_dir):
    root = Path(input_dir)
    task = json.loads((root / "task.json").read_text(encoding="utf-8"))
    reads = []
    with (root / "history.ndjson").open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                reads.append(json.loads(line))
    return task, reads


def signal_for(row, max_playing):
    rank = max(1, int(row["rank"]))
    rank_signal = math.exp(-(rank - 1) / 24.0)
    playing = row.get("playing")
    if playing is None or playing <= 0:
        return rank_signal
    activity = math.log1p(playing) / math.log1p(max_playing)
    return 0.88 * rank_signal + 0.12 * min(1.0, activity)


def estimate_strengths(reads):
    game_ids = set()
    max_playing = 1
    for read in reads:
        for row in read.get("up_and_coming") or []:
            game_ids.add(int(row["universe_id"]))
            value = row.get("playing")
            if isinstance(value, (int, float)):
                max_playing = max(max_playing, value)

    strengths = {game_id: 0.0 for game_id in game_ids}
    weights = {game_id: 0.0 for game_id in game_ids}
    previous = None
    for read in reads:
        now = timestamp(read["at"])
        if previous is not None:
            elapsed = max(0.0, (now - previous).total_seconds() / 3600.0)
            decay = math.exp(-math.log(2.0) * elapsed / HALF_LIFE_HOURS)
            for game_id in game_ids:
                strengths[game_id] *= decay
                weights[game_id] *= decay
        for row in read.get("up_and_coming") or []:
            game_id = int(row["universe_id"])
            strengths[game_id] += signal_for(row, max_playing)
            weights[game_id] += 1.0
        previous = now
    return {game_id: strengths[game_id] / weights[game_id]
            if weights[game_id] else 0.0 for game_id in game_ids}


def forecast(task, reads):
    places = int(task["places"])
    horizon = int(task.get("window", {}).get("slots", 72))
    latent = estimate_strengths(reads)
    ids = sorted(latent)
    center = sum(latent.values()) / max(1, len(latent))
    spread = math.sqrt(sum((x - center) ** 2 for x in latent.values()) /
                       max(1, len(latent)))
    scale = max(spread, 1e-9)
    baseline = {game_id: (latent[game_id] - center) / scale for game_id in ids}

    rng = random.Random(SEED)
    counts = [dict() for _ in range(places)]
    reversion = 0.25
    noise_sd = 0.17
    for _ in range(SIMULATIONS):
        current = dict(baseline)
        for hour in range(horizon):
            for game_id in ids:
                current[game_id] += reversion * (baseline[game_id] - current[game_id])
                current[game_id] += rng.gauss(0.0, noise_sd)
            ordered = sorted(ids, key=lambda game_id: current[game_id], reverse=True)
            hour_weight = math.exp(-hour / 36.0)
            for place, game_id in enumerate(ordered[:places]):
                bucket = counts[place]
                bucket[game_id] = bucket.get(game_id, 0.0) + hour_weight

    total = SIMULATIONS * sum(math.exp(-hour / 36.0) for hour in range(horizon))
    probabilities = []
    alpha = 0.15
    named_mass = 0.85
    for place in range(places):
        ranked = sorted(counts[place].items(), key=lambda item: item[1], reverse=True)
        selected = ranked[:MAX_ROWS_PER_PLACE]
        denom = total + alpha * max(1, len(ids))
        for game_id, count in selected:
            probabilities.append({
                "universe_id": game_id,
                "place": place + 1,
                "p": named_mass * (count + alpha) / denom,
            })

    top_mass = {}
    weighted_position = {}
    for place, bucket in enumerate(counts, start=1):
        for game_id, count in bucket.items():
            top_mass[game_id] = top_mass.get(game_id, 0) + count
            weighted_position[game_id] = weighted_position.get(game_id, 0.0) + place * count
    top10 = sorted(ids, key=lambda game_id: (
        -top_mass.get(game_id, 0),
        weighted_position.get(game_id, float("inf")),
        game_id,
    ))[:10]
    return {"probabilities": probabilities, "top10": top10}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    task, reads = read_inputs(input_dir)
    result = forecast(task, reads)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / task["output"]
    target.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False),
                      encoding="utf-8")


if __name__ == "__main__":
    main()
