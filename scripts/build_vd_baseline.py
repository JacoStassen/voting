#!/usr/bin/env python3
"""Build the historic baseline the projection model swings from: per voting district
(VD), the 2021 votes for each party in the eight metros, plus 2021 turnout per council.

Run once (the 2021 results are final):
  python3 scripts/build_vd_baseline.py            # writes data/baseline2021.json
  python3 scripts/build_vd_baseline.py --event 402 --year 2016 --out /tmp/b2016.json   # for backtests
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
from fetch_results import BASE, get_json  # noqa: E402

# IEC MunicipalityID for each metro (stable since 2016)
METRO_IDS = {"JHB": 3003, "TSH": 3004, "EKU": 3002, "ETH": 4005, "CPT": 9006, "NMA": 1001, "MAN": 2207, "BUF": 1117}


def vd_table(munic):
    """{vd_id: [ward_id, {party_id: valid_votes}]} — votes are ward + party ballots combined."""
    out = {}
    for w in munic.get("WardResults", []):
        for v in w.get("VotingDistrictResults", []):
            votes = {str(p["ID"]): p.get("TotalValidVotes", 0) for p in v.get("PartyBallotResults", []) if p.get("TotalValidVotes")}
            out[str(v["VotingDistrictID"])] = [w["WardID"], votes]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", type=int, default=1091)
    ap.add_argument("--year", default="2021")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "baseline2021.json"))
    a = ap.parse_args()

    base = {"event": a.event, "year": a.year, "metros": {}, "turnout": {}}
    for code, mid in METRO_IDS.items():
        m = get_json(f"{BASE}/{a.year}/EEID{a.event}Munic{mid}.js")
        if not m:
            sys.exit(f"error: no {a.year} file for {code}")
        b = (m.get("PartyBallotResults") or [{}])[0]
        base["metros"][code] = {"reg": b.get("RegisteredVoters", 0), "cast": b.get("TotalVotesCast", 0),
                                "valid": b.get("ValidVotesCast", 0), "seats": m.get("SeatsExpected", 0),
                                "vds": vd_table(m)}
        print(f"{code}: {len(base['metros'][code]['vds'])} VDs")

    # Council-level 2021 turnout for every municipality (for the national turnout model).
    nat = get_json(f"{BASE}/{a.year}/EEID{a.event}LiteMapsNational.js") or {}
    for p in nat.get("ProvinceResults", []):
        for m in p.get("MunicipalityResults", []):
            code = m.get("Municipality", "").partition(" - ")[0].strip()
            b = (m.get("PartyBallotResults") or [{}])[0]
            if b.get("RegisteredVoters"):
                base["turnout"][code] = [b["RegisteredVoters"], b.get("TotalVotesCast", 0)]

    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(base, f, separators=(",", ":"))
    print(f"wrote {out} ({os.path.getsize(out)//1024} KB, {len(base['turnout'])} councils with turnout)")


if __name__ == "__main__":
    main()
