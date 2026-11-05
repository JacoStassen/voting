#!/usr/bin/env python3
"""Project final results from a partial count: metro vote shares, seats, outright/hung
calls, turnout per metro and national turnout.

Method (swing model, the same idea broadcasters' models use):
  * For every counted voting district (VD) that also existed in 2021, compare 2026 votes
    with 2021 votes: each party's change in vote share (swing) and the change in votes cast.
  * Uncounted VDs = their 2021 result + a swing. The swing comes from counted VDs in the
    same 2026 ward, shrunk toward the swing of the most similar counted wards (judged by
    how they voted in 2021), so early-reporting areas don't skew the whole metro.
  * Resampling the counted VDs (bootstrap) gives a range and how often a party reaches
    a majority, which drives the call ("likely outright", "likely hung", "too close").
VD votes in the IEC feed add the ward and party ballots together, so turnout uses
(votes cast / 2) / registered voters.

  python3 scripts/project.py --live results/live.json --out /tmp/projections.json
  python3 scripts/project.py --backtest --base /tmp/b2016.json   # 2016 -> 2021 test
"""
import argparse, datetime, json, math, os, random, sys

sys.path.insert(0, os.path.dirname(__file__))
from fetch_results import BASE, get_json  # noqa: E402
from build_vd_baseline import METRO_IDS, vd_table  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SHRINK = 3.0      # counted VDs a ward needs before its own swing outweighs similar wards
NEIGHBOURS = 6    # similar counted wards used for wards with no counted VDs
DRAWS = 150


def shares(votes):
    t = sum(votes.values())
    return {p: v / t for p, v in votes.items()} if t else {}


def add(acc, votes, w=1.0):
    for p, v in votes.items():
        acc[p] = acc.get(p, 0.0) + v * w


def swing_of(live_sum, base_sum):
    ls, bs = shares(live_sum), shares(base_sum)
    return {p: ls.get(p, 0.0) - bs.get(p, 0.0) for p in set(ls) | set(bs)}, \
        (sum(live_sum.values()) / sum(base_sum.values()) if sum(base_sum.values()) else 1.0)


def project_once(universe, counted, base, weights=None):
    """universe: {vd: ward}; counted: {vd: {pid: votes}}; base: {vd: [ward, {pid: votes}]}.
    weights: bootstrap multiplicity per counted VD (None = all 1). Returns projected votes."""
    weights = weights or {}
    matched = [v for v in counted if v in base and sum(base[v][1].values()) > 0]
    # metro-wide and per-ward sums over matched counted VDs
    m_live, m_base, wl, wb, wn = {}, {}, {}, {}, {}
    for v in matched:
        w = weights.get(v, 1)
        if not w:
            continue
        ward = universe.get(v)
        add(m_live, counted[v], w); add(m_base, base[v][1], w)
        add(wl.setdefault(ward, {}), counted[v], w); add(wb.setdefault(ward, {}), base[v][1], w)
        wn[ward] = wn.get(ward, 0) + w
    if not m_base:
        return None
    m_swing, m_ratio = swing_of(m_live, m_base)

    # 2021 profile of every 2026 ward (for finding similar wards)
    prof_sum = {}
    for v, ward in universe.items():
        if v in base:
            add(prof_sum.setdefault(ward, {}), base[v][1])
    profile = {w: shares(s) for w, s in prof_sum.items()}
    top = sorted(shares(m_base), key=lambda p: -shares(m_base)[p])[:6]
    ward_sw = {w: swing_of(wl[w], wb[w]) for w in wl}

    def similar(ward):
        pv = profile.get(ward)
        if not pv or not ward_sw:
            return m_swing, m_ratio
        d = sorted(((sum((pv.get(p, 0) - profile.get(o, {}).get(p, 0)) ** 2 for p in top), o) for o in ward_sw))[:NEIGHBOURS]
        sw, ra, tw = {}, 0.0, 0.0
        for dist, o in d:
            k = 1.0 / (dist + 0.002)
            for p, x in ward_sw[o][0].items():
                sw[p] = sw.get(p, 0.0) + x * k
            ra += ward_sw[o][1] * k; tw += k
        return {p: x / tw for p, x in sw.items()}, ra / tw

    cache = {}

    def ward_swing(ward):
        if ward in cache:
            return cache[ward]
        prior_sw, prior_r = similar(ward)
        n = wn.get(ward, 0)
        if n:
            own_sw, own_r = ward_sw[ward]
            a = n / (n + SHRINK)
            keys = set(own_sw) | set(prior_sw)
            res = ({p: a * own_sw.get(p, 0) + (1 - a) * prior_sw.get(p, 0) for p in keys}, a * own_r + (1 - a) * prior_r)
        else:
            res = (prior_sw, prior_r)
        cache[ward] = res
        return res

    sizes = sorted(sum(b[1].values()) for b in base.values() if b[1])
    median_size = sizes[len(sizes) // 2] if sizes else 0
    total = {}
    for v, ward in universe.items():
        if v in counted:
            add(total, counted[v])
            continue
        sw, ratio = ward_swing(ward)
        if v in base and sum(base[v][1].values()):
            bs = shares(base[v][1])
            size = sum(base[v][1].values()) * ratio
        else:  # new VD: use the ward's projected profile at a typical size
            bs = profile.get(ward) or shares(m_base)
            size = median_size * ratio
        sh = {p: max(0.0, bs.get(p, 0.0) + sw.get(p, 0.0)) for p in set(bs) | set(sw)}
        t = sum(sh.values()) or 1.0
        add(total, {p: x / t * size for p, x in sh.items()})
    return total


def allocate(votes, seats):
    """Largest-remainder share-out of council seats on the projected vote."""
    tot = sum(votes.values())
    if not tot or not seats:
        return {}
    quota = tot / seats
    alloc = {p: int(v // quota) for p, v in votes.items()}
    rem = sorted(votes, key=lambda p: -(votes[p] / quota - alloc[p]))
    for p in rem[: seats - sum(alloc.values())]:
        alloc[p] += 1
    return {p: s for p, s in alloc.items() if s}


def perturb(votes, coverage, rng):
    """Add model error on top of sampling error. Counting order is not random (whole
    areas report together), and backtests on 2016->2021 showed errors of up to ~6 points
    at 10-25% counted when one party's strongholds report first. Shared-scale noise
    that shrinks as the count completes keeps calls honest."""
    tot = sum(votes.values())
    if not tot:
        return votes
    sigma = 0.035 * (1 - coverage) + 0.004
    sh = {p: max(0.0, v / tot + rng.gauss(0, sigma * math.sqrt(min(1.0, (v / tot) / 0.3)))) for p, v in votes.items()}
    t = sum(sh.values()) or 1.0
    return {p: x / t * tot for p, x in sh.items()}


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))] if xs else 0


def project_metro(universe, counted, base, seats, reg, cast_ratio, rng):
    covered = sum(sum(base[v][1].values()) for v in counted if v in base)
    base_total = sum(sum(b[1].values()) for b in base.values())
    coverage = covered / base_total if base_total else 0
    out = {"vds": [len(counted), len(universe)], "coverage": round(coverage, 3)}
    if coverage < 0.03 or len(counted) < 10:
        out["call"] = {"k": "early", "text": "Too early to call"}
        return out
    point = project_once(universe, counted, base)
    vds = list(counted)
    draws = []
    for _ in range(DRAWS):
        wts = {}
        for _ in vds:
            v = vds[rng.randrange(len(vds))]
            wts[v] = wts.get(v, 0) + 1
        res = project_once(universe, {v: counted[v] for v in wts}, base, wts)
        if res:
            draws.append(perturb(res, coverage, rng))
    tot = sum(point.values())
    parties = sorted(point, key=lambda p: -point[p])
    need = seats // 2 + 1
    seat_draws = [allocate(d, seats) for d in draws]
    proj = []
    for p in parties[:8]:
        sh = [d.get(p, 0) / sum(d.values()) * 100 for d in draws]
        st = [s.get(p, 0) for s in seat_draws]
        if point[p] / tot < 0.005:
            continue
        proj.append([int(p), round(point[p] / tot * 100, 1), round(pct(sh, .05), 1), round(pct(sh, .95), 1),
                     allocate(point, seats).get(p, 0), pct(st, .05), pct(st, .95)])
    lead = parties[0]
    p_major = sum(1 for s in seat_draws if s.get(lead, 0) >= need) / len(seat_draws)
    p_lead = sum(1 for d in draws if max(d, key=d.get) == lead) / len(draws)
    # Early in the count, cap confidence: counting order is not random.
    cap = 0.9 if coverage < 0.15 else 0.97
    p_major_c, p_lead_c = min(p_major, cap), min(p_lead, cap)
    if p_major >= 0.9:
        k, text = "won", "outright"
    elif p_major <= 0.1 and p_lead >= 0.9:
        k, text = "hung", "hung"
    elif p_major <= 0.1:
        k, text = "hung", "hung, unclear who is largest"
    else:
        k, text = "close", "too close to call"
    out.update({"seats": seats, "need": need, "proj": proj, "lead": int(lead),
                "p_major": round(p_major_c, 2), "p_lead": round(p_lead_c, 2),
                "call": {"k": k, "text": text}})
    if reg and cast_ratio:
        # Turnout is far more sensitive to counting order than vote shares (2016->2021
        # backtests: up to ~12 points off at 25% counted), so widen its range accordingly.
        tsig = 0.10 * (1 - coverage) + 0.01
        tv = [sum(d.values()) * cast_ratio / 2 / reg * 100 * (1 + rng.gauss(0, tsig)) for d in draws]
        out["turnout"] = [round(tot * cast_ratio / 2 / reg * 100, 1), round(pct(tv, .05), 1), round(pct(tv, .95), 1)]
    return out


def national_turnout(live, base_turnout, metro_turnout):
    """Council-level estimate: observed councils use (cast/2)/(registered x share of VDs
    counted); the rest use their 2021 turnout times the typical 2026/2021 ratio."""
    obs, rows = [], []
    for code, m in live["munis"].items():
        reg = m["turnout"]["reg"]
        f = m["prog"]["vd"][0] / m["prog"]["vd"][1] if m["prog"]["vd"][1] else 0
        b = base_turnout.get(code)
        t21 = b[1] / 2 / b[0] if b and b[0] else None
        if code in metro_turnout:
            t = metro_turnout[code] / 100
        elif f >= 0.1 and reg:
            t = m["turnout"]["cast"] / 2 / (reg * f)
        else:
            t = None
        if t is not None and t21:
            obs.append(t / t21)
        rows.append((reg, t, t21))
    if len(obs) < 5:
        return None
    ratios = sorted(obs)

    def total(ratio):
        num = den = 0
        for reg, t, t21 in rows:
            tt = t if t is not None else (t21 * ratio if t21 else None)
            if tt is not None and reg:
                num += reg * tt; den += reg
        return num / den * 100 if den else None

    mid = total(ratios[len(ratios) // 2])
    # Outside the metros we only know the share of VDs counted, not the share of voters,
    # and rural VDs are small, so this tends to read low. Use a wide, asymmetric range.
    return {"mid": round(mid, 1), "lo": round(total(pct(ratios, .1)), 1), "hi": round(max(total(pct(ratios, .9)), mid + 4), 1),
            "councils": len(obs), "t2021": round(sum(b[1] for b in base_turnout.values()) / 2 / sum(b[0] for b in base_turnout.values()) * 100, 1)}


def live_counted(munic):
    universe, counted = {}, {}
    for v, (ward, votes) in vd_table(munic).items():
        universe[v] = ward
        if votes:
            counted[v] = votes
    return universe, counted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", type=int, default=1887)
    ap.add_argument("--year", default="2026")
    ap.add_argument("--live", default=os.path.join(HERE, "..", "results", "live.json"))
    ap.add_argument("--base", default=os.path.join(HERE, "..", "data", "baseline2021.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results", "projections.json"))
    ap.add_argument("--raw-dir", help="read metro council files saved by fetch_results.py --raw-dir (fetch if missing or older than 10 minutes)")
    ap.add_argument("--backtest", action="store_true", help="treat 2021 as the live count with --base 2016")
    a = ap.parse_args()
    rng = random.Random(42)
    base = json.load(open(a.base))
    if a.backtest:
        return backtest(base, rng)

    live = json.load(open(a.live))
    out = {"v": 1, "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "report": live.get("report"), "metros": {}}
    metro_t = {}
    for code, mid in METRO_IDS.items():
        m, path = None, a.raw_dir and os.path.join(a.raw_dir, f"{code}.json")
        if path and os.path.exists(path) and datetime.datetime.now().timestamp() - os.path.getmtime(path) < 600:
            m = json.load(open(path))
        if not m:
            m = get_json(f"{BASE}/{a.year}/EEID{a.event}Munic{mid}.js")
        lm = live["munis"].get(code)
        if not m or not lm:
            continue
        universe, counted = live_counted(m)
        t = lm["turnout"]
        res = project_metro(universe, counted, base["metros"][code]["vds"], m.get("SeatsExpected") or lm["prog"]["seats"][1],
                            t["reg"], (t["cast"] / t["valid"]) if t["valid"] else 0, rng)
        out["metros"][code] = res
        if "turnout" in res:
            metro_t[code] = res["turnout"][0]
        print(f"{code}: {res['call']['text']} ({res.get('coverage')})", file=sys.stderr)
    out["turnout"] = national_turnout(live, base["turnout"], metro_t)
    with open(a.out, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"wrote {a.out}")


def backtest(base, rng):
    """Use 2021 as if it were being counted, 2016 as the baseline. Count 25% of VDs in
    three orders (random, DA-strongest first, ANC-strongest first) and compare."""
    for code, mid in METRO_IDS.items():
        m = get_json(f"{BASE}/2021/EEID1091Munic{mid}.js")
        universe, full = live_counted(m)
        actual = shares({p: v for vd in full.values() for p, v in vd.items()} and
                        {p: sum(vd.get(p, 0) for vd in full.values()) for p in {p for vd in full.values() for p in vd}})
        seats = m["SeatsExpected"]
        act_seats = allocate({p: actual[p] for p in actual}, seats)
        lead = max(actual, key=actual.get)
        line = [f"{code}: actual {lead} {actual[lead]*100:.1f}% {'majority' if act_seats.get(lead,0) >= seats//2+1 else 'hung'}"]
        for order in ("random", "52", "7"):
            vds = list(full)
            if order == "random":
                rng.shuffle(vds)
            else:
                vds.sort(key=lambda v: -shares(full[v]).get(order, 0))
            for frac in (0.1, 0.25):
                counted = {v: full[v] for v in vds[: int(len(vds) * frac)]}
                r = project_metro(universe, counted, base["metros"][code]["vds"], seats, 0, 0, rng)
                pr = {str(x[0]): x for x in r.get("proj", [])}
                err = max((abs(pr[p][1] - actual.get(p, 0) * 100) for p in pr), default=0)
                cur = shares({p: sum(vd.get(p, 0) for vd in counted.values()) for p in {p for vd in counted.values() for p in vd}})
                raw = max(abs(cur.get(p, 0) - actual.get(p, 0)) * 100 for p in actual if actual[p] > .02)
                line.append(f"{order[:6]}@{int(frac*100)}%: {r['call']['text']}, max err {err:.1f}pp (raw count {raw:.1f}pp)")
        print("\n  ".join(line))


if __name__ == "__main__":
    main()
