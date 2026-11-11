import json
import math
import os
import random
from datetime import datetime


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def poisson(rng, rate):
    limit = math.exp(-rate)
    product = 1.0
    count = 0
    while product > limit:
        count += 1
        product *= rng.random()
    return count - 1


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    with open(os.path.join(input_dir, "task.json"), encoding="utf-8") as f:
        task = json.load(f)
    reads = []
    with open(os.path.join(input_dir, "history.ndjson"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                reads.append(json.loads(line))

    times = [timestamp(read["at"]) for read in reads]
    ids = set()
    observations = {}
    creations = {}
    new_arrivals = []
    for read_i, read in enumerate(reads):
        for row in read.get("up_and_coming") or []:
            uid = int(row["universe_id"])
            rank = int(row["rank"])
            ids.add(uid)
            observations.setdefault(uid, []).append((times[read_i], -math.log(max(1, rank)), rank))
        if read_i:
            previous_ids = {int(r["universe_id"]) for r in (reads[read_i - 1].get("up_and_coming") or [])}
            new_arrivals.extend(-math.log(max(1, int(row["rank"])))
                                for row in (read.get("up_and_coming") or [])
                                if int(row["universe_id"]) not in previous_ids)
        details = read.get("details")
        if details:
            for key, info in details.items():
                if info and info.get("created"):
                    try:
                        creations[int(key)] = timestamp(info["created"])
                    except (ValueError, TypeError):
                        pass

    end = times[-1]
    places = int(task["places"])
    slots = int(task["window"]["slots"])
    hours = max(1, slots * int(task["window"].get("slot_minutes", 60)) // 60)
    candidates = []
    for uid in ids:
        obs = observations[uid]
        if obs[-1][0] >= end - 96 * 3600 or any(t >= end - 72 * 3600 and rank <= 25 for t, _, rank in obs):
            candidates.append(uid)

    levels, drifts, velocities, peaks = {}, {}, {}, {}
    floor_s = -math.log(110.0)
    for uid in candidates:
        obs = observations[uid]
        recent_s = [value for t, value, _ in obs if t >= end - 96 * 3600]
        peaks[uid] = max(recent_s) if recent_s else floor_s
        recent = [(t / 3600.0, value, math.exp(-(end - t) / (24 * 3600)))
                  for t, value, _ in obs if t >= end - 48 * 3600]
        if len(recent) >= 3:
            velocity_weight = sum(w for _, _, w in recent)
            velocity_mean_x = sum(x * w for x, _, w in recent) / velocity_weight
            velocity_mean_y = sum(y * w for _, y, w in recent) / velocity_weight
            velocity_denom = sum(w * (x - velocity_mean_x) ** 2 for x, _, w in recent)
            velocity_slope = (
                sum(w * (x - velocity_mean_x) * (y - velocity_mean_y)
                    for x, y, w in recent) / velocity_denom
                if velocity_denom else 0.0
            )
            velocity = velocity_slope * len(recent) / (len(recent) + 4.0)
        else:
            velocity = 0.0
        velocities[uid] = max(-0.10, min(0.10, velocity))
        weighted = [(v, math.exp(-(end - t) / (4 * 3600))) for t, v, _ in obs]
        levels[uid] = sum(v * w for v, w in weighted) / sum(w for _, w in weighted)
        fit = []
        start = end - 120 * 3600
        previous = {t: v for t, v, _ in obs if t >= start}
        for t in times:
            if t < start:
                continue
            value = previous.get(t, floor_s)
            fit.append((t / 3600.0, value, math.exp(-(end - t) / (48 * 3600))))
        sw = sum(w for _, _, w in fit)
        mx = sum(x * w for x, _, w in fit) / sw
        my = sum(y * w for _, y, w in fit) / sw
        denom = sum(w * (x - mx) ** 2 for x, _, w in fit)
        slope = (sum(w * (x - mx) * (y - my) for x, y, w in fit) / denom) if denom else 0.0
        residual = sum(w * (y - my - slope * (x - mx)) ** 2 for x, y, w in fit) / max(sw, 1e-9)
        evidence = min(1.0, len(obs) / 8.0) * (1.0 / (1.0 + 0.8 * residual))
        drifts[uid] = max(-0.035, min(0.035, slope * evidence))

    sq, exposure = 0.0, 0.0
    for i in range(1, len(reads)):
        dt = max(1e-6, (times[i] - times[i - 1]) / 3600.0)
        before = {int(r["universe_id"]): int(r["rank"]) for r in (reads[i - 1].get("up_and_coming") or [])}
        for row in reads[i].get("up_and_coming") or []:
            uid = int(row["universe_id"])
            if uid in before:
                delta = -math.log(max(1, int(row["rank"]))) + math.log(max(1, before[uid]))
                sq += delta * delta
                exposure += dt
    sigma = max(0.025, min(0.15, math.sqrt(sq / max(exposure, 1e-9)))) * 1.12

    new_rate = len(new_arrivals) / max(1.0, (end - times[0]) / 3600.0)
    entrant_mean = sum(new_arrivals) / len(new_arrivals) if new_arrivals else floor_s
    entrant_var = (sum((x - entrant_mean) ** 2 for x in new_arrivals) / max(1, len(new_arrivals))) ** 0.5 if new_arrivals else 0.35
    entrant_mean = max(-4.3, min(-2.3, entrant_mean))

    rng = random.Random(702041)
    simulations = 1500
    occupancy = {uid: [0] * places for uid in candidates}
    entrant_occ = [0] * places
    slot_count = simulations * hours
    sorted_candidates = sorted(candidates)
    for _ in range(simulations):
        strength = {uid: levels[uid] for uid in candidates}
        jumps = {}
        for uid in sorted_candidates:
            start_rank = math.exp(-levels[uid])
            if start_rank <= 10:
                jump_probability = 0.0
            elif start_rank <= 20:
                jump_probability = 0.10
            elif start_rank <= 35:
                jump_probability = 0.07
            elif start_rank <= 60:
                jump_probability = 0.055
            else:
                jump_probability = 0.04
            if rng.random() < jump_probability:
                jumps[uid] = max(0.6, min(3.2, rng.gauss(1.7, 0.55)))
            else:
                jumps[uid] = 0.0
        entrants = []
        for h in range(1, hours + 1):
            damping = 1.0 / (1.0 + h / 36.0)
            for uid in sorted_candidates:
                z = rng.gauss(0.0, 1.0)
                chi = rng.gammavariate(2.5, 2.0)
                strength[uid] += (drifts[uid] * damping + velocities[uid] * math.exp(-h / 30.0)
                                  + 0.01 * max(0.0, peaks[uid] - strength[uid])
                                  + sigma * z / math.sqrt(chi / 5.0))
            age_time = end + h * 3600
            entrants = [(s, birth, drift) for s, birth, drift in entrants if age_time - birth <= 28 * 86400]
            for _n in range(poisson(rng, new_rate)):
                s = max(-5.5, min(-1.4, rng.gauss(entrant_mean, max(0.15, entrant_var))))
                entrants.append((s, age_time, rng.uniform(0.0, 0.012)))
            updated = []
            for s, birth, drift in entrants:
                z = rng.gauss(0.0, 1.0)
                chi = rng.gammavariate(2.5, 2.0)
                updated.append((s + drift * damping + sigma * z / math.sqrt(chi / 5.0), birth, drift))
            entrants = updated
            jump_phase = min(1.0, h / 18.0)
            ranked = [(s + jumps[uid] * jump_phase, uid, False) for uid, s in strength.items()
                      if uid not in creations or age_time - creations[uid] <= 28 * 86400]
            ranked.extend((s, None, True) for s, _, _ in entrants)
            ranked.sort(key=lambda item: item[0], reverse=True)
            for place, (_, uid, is_entrant) in enumerate(ranked[:places]):
                if is_entrant:
                    entrant_occ[place] += 1
                else:
                    occupancy[uid][place] += 1

    probabilities = []
    for place in range(places):
        raw_named = sum(occupancy[uid][place] for uid in candidates) / slot_count
        reserve = min(0.55, max(0.15, entrant_occ[place] / slot_count))
        scale = min(1.0, max(0.0, 1.0 - reserve) / raw_named) if raw_named else 0.0
        rows = [((occupancy[uid][place] + 0.25) /
                 (slot_count + 0.25 * max(1, len(candidates))) * scale, uid)
                for uid in candidates]
        tempered = [(p ** 0.85, uid) for p, uid in rows]
        tempered_sum = sum(p for p, _ in tempered)
        target_mass = 1.0 - reserve
        if tempered_sum:
            rows = [(p * target_mass / tempered_sum, uid) for p, uid in tempered]
        else:
            rows = [(0.0, uid) for _, uid in rows]
        rows.sort(reverse=True)
        for p, uid in rows[:100]:
            if p >= 0.00005:
                probabilities.append({"universe_id": uid, "place": place + 1, "p": round(p, 8)})

    top_scores = {uid: sum((places - place) * occupancy[uid][place] for place in range(places))
                  for uid in candidates}
    top10 = [uid for uid, _ in sorted(top_scores.items(), key=lambda item: (-item[1], item[0]))[:10]]
    output_name = task.get("output", "forecast.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, output_name), "w", encoding="utf-8") as f:
        json.dump({"probabilities": probabilities, "top10": top10}, f, separators=(",", ":"), ensure_ascii=False)


if __name__ == "__main__":
    main()
