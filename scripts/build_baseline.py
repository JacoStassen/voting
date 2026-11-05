#!/usr/bin/env python3
"""Build results/base2021.json: the 2021 local-election result per council, province and
nationally, so the live page can show the swing since 2021. Run once; it fetches every
council's full results file from the IEC dashboard (about 30 MB compressed).

Usage: python3 scripts/build_baseline.py
"""
import concurrent.futures, json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
from fetch_results import BASE, IEC_PROV, get_json  # noqa: E402

EVENT, YEAR = 1091, "2021"


def rows(prs, min_pct=0.3):
    """[[partyId, pct, seats], ...] for parties above min_pct or with seats."""
    out = [[b["ID"], b.get("PercOfVotes", 0), b.get("TotalSeatsWon", 0)] for b in prs or []]
    return sorted([r for r in out if r[1] >= min_pct or r[2]], key=lambda r: -r[1])


def turnout(prs):
    """[registered, ballots cast] from a results block."""
    b = (prs or [{}])[0]
    return [b.get("RegisteredVoters", 0), b.get("TotalVotesCast", 0)]


def main():
    base = f"{BASE}/{YEAR}/EEID{EVENT}"
    nat = get_json(f"{base}LiteMapsNational.js") or sys.exit("national feed unavailable")
    plist = {p["ID"]: p for p in get_json(f"{BASE}/2016/PartyList.js") or []}
    out = {"year": YEAR, "nat": rows(nat.get("PartyBallotResults"), 0.1), "prov": {}, "munis": {},
           "t": {"nat": turnout(nat.get("PartyBallotResults")), "prov": {}}}
    todo = []
    for pid in range(1, 10):
        p = get_json(f"{base}Province{pid}.js") or sys.exit(f"province {pid} unavailable")
        out["prov"][IEC_PROV[pid]] = rows(p.get("PartyBallotResults"), 0.1)
        out["t"]["prov"][IEC_PROV[pid]] = turnout(p.get("PartyBallotResults"))
        for m in p.get("MunicipalityResults", []):
            code = m.get("Municipality", "").partition(" - ")[0].strip()
            todo.append((code, m["MunicipalityID"], m.get("SeatsExpected", 0)))

    def one(t):
        code, mid, seats = t
        return code, seats, get_json(f"{base}Munic{mid}.js")

    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        for i, (code, seats, full) in enumerate(ex.map(one, todo), 1):
            if not full:
                print(f"warn: no data for {code}", file=sys.stderr)
                continue
            out["munis"][code] = {"seats": seats, "res": rows(full.get("PartyBallotResults")),
                                  "t": turnout(full.get("PartyBallotResults"))}
            print(f"{i}/{len(todo)} {code}", file=sys.stderr, end="\r")

    used = {r[0] for r in out["nat"]} | {r[0] for v in out["prov"].values() for r in v} | \
           {r[0] for m in out["munis"].values() for r in m["res"]}
    out["parties"] = {str(i): [plist[i]["Name"], plist[i]["sWebColour"]] for i in sorted(used) if i in plist}
    dest = os.path.join(os.path.dirname(__file__), "..", "results", "base2021.json")
    with open(dest, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"\nwrote {dest}: {len(out['munis'])} councils, {os.path.getsize(dest) // 1024} KB")


if __name__ == "__main__":
    main()
