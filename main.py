#!/usr/bin/env python3
"""Forecaster for make.fun's roblox-up-and-coming-forecast-01.

Reads the Up-and-Coming chart history in /input (history.ndjson + task.json)
and writes one static forecast to /output/forecast.json: for each of the top
10 places, a probability for each named game holding that place at a
randomly chosen hour of the scored window, plus a top-10 guess.

Method: every game is given a latent chart strength s = -ln(rank). From its
rank track (absences imputed just below the chart's foot) an exponentially
weighted level (12 h half-life) and a shrunk, capped drift are fitted; the
per-hour random-walk sigma of s and the first-appearance strength
distribution are fitted from the history itself. A seeded Monte Carlo then
walks all candidate strengths forward over the window's hours, hour by
hour, while phantom newcomers arrive as a Poisson stream with strengths
drawn from that first-appearance distribution and positive-biased drift,
and games whose Roblox creation date (when the history carries details)
passes 28 days age out of the chart. The share of simulations in which each
game holds each place, averaged over hours, is its occupancy; occupancies
are flattened (exponent 0.5) into the place's named mass, each place
keeping an unnamed share at least as large as the phantom share, so games
nobody can name yet are still covered by the scorer's unnamed-share rule.

Deterministic: fixed seed, sorted output, no wall clock, no network.
Python 3.13 standard library only.
"""
import json
import math
import os
import random
from datetime import datetime

PARAMS = {
    "halflife_h": 12.0,        # EWMA half-life for the latent level
    "drift_window_h": 120.0,   # lookback for the drift regression
    "drift_shrink": 6.0,       # pseudo-observations shrinking drift to 0
    "drift_cap": 0.012,        # max |drift| per hour in latent units
    "drift_damp_h": 60.0,      # hourly drift factor 1/(1+h/damp): saturating
    "sigma_scale": 1.2,        # multiplier on the fitted walk sigma
    "gamma": 0.5,              # calibration exponent on occupancy
    "resid_min": 0.12,         # minimum unnamed share per place
    "resid_phantom_mult": 1.0, # phantom share -> residual allowance
    "row_min_p": 0.0015,       # drop probability rows below this
    "sims": 1200,
    "seed": 20261113,
    "offchart_s": -5.0,        # latent imputed for a read where a game is absent
    "candidate_s": -4.25,      # keep games whose level is above this (~rank 70)
}


def parse_iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def load_reads(input_dir):
    task = json.load(open(os.path.join(input_dir, "task.json")))
    reads = []
    created = {}
    with open(os.path.join(input_dir, "history.ndjson")) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            t = parse_iso(r["at"])
            chart = {}
            for row in r["up_and_coming"]:
                chart[row["universe_id"]] = (row["rank"], row.get("playing"))
            reads.append((t, chart))
            det = r.get("details")
            if isinstance(det, dict):
                for gid, d in det.items():
                    if isinstance(d, dict) and d.get("created"):
                        created[int(gid)] = parse_iso(d["created"])
    reads.sort(key=lambda x: x[0])
    return task, reads, created


def fit_sigma(reads):
    """Per-hour random-walk sigma of latent s = -ln(rank), from read pairs."""
    num = 0.0
    den = 0.0
    for (t0, c0), (t1, c1) in zip(reads, reads[1:]):
        dt = (t1 - t0) / 3600.0
        if dt <= 0 or dt > 16:
            continue
        for g, (r0, _) in c0.items():
            if g in c1:
                ds = -math.log(c1[g][0]) + math.log(r0)
                num += ds * ds
                den += dt
    if den == 0:
        return 0.045
    return math.sqrt(max(num / den, 1e-4))


def entry_strengths(reads):
    """Latent strengths at first appearance (absent from the previous read)."""
    vals = []
    prev = set()
    for _, chart in reads:
        cur = set(chart)
        for g in cur - prev:
            vals.append(-math.log(chart[g][0]))
        prev = cur
    return vals


def game_tracks(reads):
    """Per game: (hours from first read, rank or None) at every read."""
    t0 = reads[0][0]
    games = {}
    for t, chart in reads:
        th = (t - t0) / 3600.0
        for g in games:
            if g not in chart:
                games[g].append((th, None))
        for g, (rank, _playing) in chart.items():
            games.setdefault(g, []).append((th, rank))
    return games


def level_and_drift(track, t_end_h, p):
    """EWMA latent level at t_end_h and shrunk drift (latent units/hour)."""
    hl = p["halflife_h"]
    wsum = 0.0
    ssum = 0.0
    for th, rank in track:
        s = -math.log(rank) if rank else p["offchart_s"]
        w = 0.5 ** ((t_end_h - th) / hl)
        wsum += w
        ssum += w * s
    level = ssum / wsum if wsum else p["offchart_s"]
    pts = [
        (th, -math.log(rank) if rank else p["offchart_s"])
        for th, rank in track
        if t_end_h - th <= p["drift_window_h"]
    ]
    if len(pts) >= 3:
        n = len(pts)
        mt = sum(x for x, _ in pts) / n
        ms = sum(y for _, y in pts) / n
        cov = sum((x - mt) * (y - ms) for x, y in pts)
        var = sum((x - mt) ** 2 for x, _ in pts)
        slope = cov / var if var > 0 else 0.0
        shrink = n / (n + p["drift_shrink"])
        drift = max(-p["drift_cap"], min(p["drift_cap"], slope * shrink))
    else:
        drift = 0.0
    return level, drift


def forecast(reads, created, horizon_h, p):
    games = game_tracks(reads)
    t_end_h = (reads[-1][0] - reads[0][0]) / 3600.0
    window_start = reads[-1][0]
    sigma = fit_sigma(reads) * p["sigma_scale"]
    entries = sorted(entry_strengths(reads))
    span_h = max((reads[-1][0] - reads[0][0]) / 3600.0, 1.0)
    lam_per_h = len(entries) / span_h  # first appearances per hour
    states = {}
    for g, track in games.items():
        level, drift = level_and_drift(track, t_end_h, p)
        best = min(r for _, r in track if r)
        if level > p["candidate_s"] or best <= 40:
            states[g] = (level, drift)
    rng = random.Random(p["seed"])
    sims = p["sims"]
    hours = int(horizon_h)
    occ = {}  # (game, place) -> count; game -1 is the phantom pool
    for _ in range(sims):
        lat = {g: v[0] for g, v in states.items()}
        drift = {g: v[1] for g, v in states.items()}
        phantoms = []  # [latent, drift]
        for h in range(1, hours + 1):
            damp = 1.0 / (1.0 + h / p["drift_damp_h"])
            for g in lat:
                lat[g] += drift[g] * damp + rng.gauss(0.0, sigma)
            for ph in phantoms:
                ph[0] += ph[1] + rng.gauss(0.0, sigma)
            # Poisson(lam_per_h) arrivals by Knuth's method
            limit = math.exp(-lam_per_h)
            k = 0
            prob = 1.0
            while True:
                prob *= rng.random()
                if prob <= limit:
                    break
                k += 1
            for _ in range(k):
                s0 = entries[rng.randrange(len(entries))] if entries else -4.0
                d0 = max(0.0, rng.gauss(0.004, 0.004))
                phantoms.append([s0, d0])
            if created:
                now = window_start + h * 3600.0
                for g in list(lat):
                    c = created.get(g)
                    if c and (now - c) > 28 * 86400:
                        del lat[g]
            vals = [(v, g) for g, v in lat.items()] + [(ph[0], -1) for ph in phantoms]
            vals.sort(key=lambda x: -x[0])
            for place, (_, g) in enumerate(vals[:10], start=1):
                occ[(g, place)] = occ.get((g, place), 0) + 1
    total = sims * hours
    places = {}
    phantom_share = {}
    for (g, k), v in occ.items():
        share = v / total
        if g == -1:
            phantom_share[k] = share
        else:
            places.setdefault(k, {})[g] = share
    rows = []
    game_score = {}
    for k in range(1, 11):
        cand = places.get(k, {})
        if not cand:
            continue
        resid = max(p["resid_min"], phantom_share.get(k, 0.0) * p["resid_phantom_mult"])
        resid = min(resid, 0.6)
        mass = 1.0 - resid
        wts = {g: v ** p["gamma"] for g, v in cand.items()}
        wsum = sum(wts.values())
        for g, w in wts.items():
            pg = mass * w / wsum
            if pg >= p["row_min_p"]:
                rows.append({"universe_id": g, "place": k, "p": round(pg, 6)})
                game_score[g] = game_score.get(g, 0.0) + pg * (11 - k)
    rows.sort(key=lambda r: (r["place"], -r["p"], r["universe_id"]))
    top10 = [g for g, _ in sorted(game_score.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    return {"probabilities": rows, "top10": top10}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    task, reads, created = load_reads(input_dir)
    horizon = task.get("window", {}).get("slots", 72)
    fc = forecast(reads, created, horizon, PARAMS)
    out_path = os.path.join(output_dir, task.get("output", "forecast.json"))
    with open(out_path, "w") as f:
        f.write(json.dumps(fc) + "\n")


if __name__ == "__main__":
    main()
