#!/usr/bin/env python3
"""Fetch live local-election results from the IEC results dashboard and write a
compact JSON file the static site can read from its own origin.

The IEC feed (results.elections.org.za/dashboards/lge/MapsJason/...) sends no CORS
headers, so browsers on other sites cannot read it directly. A GitHub Action runs
this script every few minutes and commits results/live.json.

Usage:
  python3 scripts/fetch_results.py                      # 2026 (event 1887)
  python3 scripts/fetch_results.py --event 1091 --year 2021 --out /tmp/r.json
"""
import argparse, concurrent.futures, datetime, gzip, json, os, re, sys, time, urllib.error, urllib.request

BASE = "https://results.elections.org.za/dashboards/lge/MapsJason"
UA = "KnowYourBallot-results-relay/1.0 (+https://voting.stassen.org.za)"

# IEC ProvinceID -> site province key
IEC_PROV = {1: "EC", 2: "FS", 3: "GP", 4: "KZN", 5: "MP", 6: "NC", 7: "LIM", 8: "NW", 9: "WC"}
# Municipal Demarcation Board province digit (first digit of an 8-digit ward ID)
MDB_DIGIT = {"WC": "1", "EC": "2", "NC": "3", "FS": "4", "KZN": "5", "NW": "6", "GT": "7", "GP": "7", "MP": "8", "LIM": "9"}
# Metro ward-ID prefixes (first five digits)
METRO_PREFIX = {"CPT": "19100", "BUF": "29200", "NMA": "29300", "MAN": "49400",
                "ETH": "59500", "EKU": "79700", "JHB": "79800", "TSH": "79900"}


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/javascript, */*; q=0.01",
                                                      "Accept-Encoding": "gzip",
                                                      "Referer": "https://results.elections.org.za/dashboards/lge/"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                raw = raw.decode("utf-8-sig")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # not published yet
            err = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            err = e
        time.sleep(2 * (i + 1))
    print(f"warn: {url}: {err}", file=sys.stderr)
    return None


def ward_prefix(code):
    """'EC101' -> '21001', 'KZN225' -> '52205', 'JHB' -> '79800'."""
    if code in METRO_PREFIX:
        return METRO_PREFIX[code]
    m = re.fullmatch(r"([A-Z]+)(\d{2})(\d)", code)
    if not m or m.group(1) not in MDB_DIGIT:
        return None
    return MDB_DIGIT[m.group(1)] + m.group(2) + m.group(3).zfill(2)


def prog(o):
    return {
        "vd": [o.get("VDsComplete", 0), o.get("VDExpected", 0)],
        "wards": [o.get("WardsComplete", 0), o.get("WardExpected", 0)],
        "munis": [o.get("MuncipalitiesComplete", 0), o.get("MunicExpected", 0)],
        "seats": [o.get("SeatsComplete", 0), o.get("SeatsExpected", 0)],
        "hung": o.get("HungCouncils", 0), "majority": o.get("MajorityCouncils", 0),
        "pct": o.get("Perc_VDsComplete", 0),
    }


def results(rows, used):
    """[id, votes, pct, wardSeats, prSeats, totalSeats, councilsWon, majoritiesWon, isCouncilWinner]"""
    out = []
    for b in rows or []:
        pid = b["ID"]
        used.add(pid)
        out.append([pid, b.get("TotalValidVotes", 0), b.get("PercOfVotes", 0), b.get("WardSeatsWon", 0),
                    b.get("PRSeatsWon", 0), b.get("TotalSeatsWon", 0), b.get("CouncilsWon", 0),
                    b.get("MajorityWon", 0), 1 if b.get("IsCouncilWinner") else 0])
    out.sort(key=lambda r: (-r[5], -r[1]))
    return out


def turnout(rows):
    b = (rows or [{}])[0]
    return {"reg": b.get("RegisteredVoters", 0), "cast": b.get("TotalVotesCast", 0),
            "valid": b.get("ValidVotesCast", 0), "spoilt": b.get("SpoiltVotes", 0)}


FULL_EVERY = 300   # refetch a non-metro council's full party list at most every 5 minutes
FULL_MAX = 40      # and at most this many full files per run (each is ~100-300 KB gzipped)


def fetch_full(base, data, prev, used):
    """The province feed lists only each council's top three parties. The per-council
    file (EEID...Munic{id}.js) has every party but is large, so fetch it only for
    councils whose count moved, metros first, and reuse the last copy otherwise."""
    now = int(time.time())
    pm = (prev or {}).get("munis", {})
    todo = []
    for code, m in data["munis"].items():
        old = pm.get(code) or {}
        if old.get("all"):
            m["all"], m["ft"] = old["all"], old.get("ft", 0)
            used.update(r[0] for r in m["all"])
        if not m.get("mid") or not m["prog"]["vd"][0]:
            continue
        moved = old.get("prog", {}).get("vd") != m["prog"]["vd"] or old.get("prog", {}).get("seats") != m["prog"]["seats"]
        if not m.get("all") or (moved and (code in METRO_PREFIX or now - m.get("ft", 0) >= FULL_EVERY)):
            todo.append(code)
    todo.sort(key=lambda c: (c not in METRO_PREFIX, data["munis"][c].get("ft", 0)))
    todo = todo[:FULL_MAX]

    def one(code):
        return code, get_json(f"{base}Munic{data['munis'][code]['mid']}.js", tries=2)

    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        for code, full in ex.map(one, todo):
            rows = (full or {}).get("PartyBallotResults")
            if not rows:
                continue
            res = [r for r in results(rows, set()) if r[1] or r[5]][:30]
            used.update(r[0] for r in res)
            data["munis"][code]["all"], data["munis"][code]["ft"] = res, now
    if todo:
        print(f"full party lists: fetched {len(todo)} councils", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", type=int, default=1887)
    ap.add_argument("--year", default="2026")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "results", "live.json"))
    a = ap.parse_args()

    base = f"{BASE}/{a.year}/EEID{a.event}"
    nat = get_json(f"{base}LiteMapsNational.js")
    if not nat:
        sys.exit("error: national feed unavailable")
    plist = get_json(f"{BASE}/2016/PartyList.js") or []
    pmeta = {p["ID"]: p for p in plist}

    out = os.path.abspath(a.out)
    try:
        prev = json.load(open(out))
        if prev.get("event") != a.event:
            prev = None
    except (OSError, ValueError):
        prev = None

    used = set()
    data = {
        "v": 1, "event": a.event, "year": a.year,
        "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "report": nat.get("ReportDate"),
        "prog": prog(nat), "turnout": turnout(nat.get("PartyBallotResults")),
        "nat": results(nat.get("PartyBallotResults"), used),
        "prov": [], "munis": {},
    }

    prefix_to_code = {}
    failed = []
    for pid in range(1, 10):
        p = get_json(f"{base}Province{pid}.js")
        key = IEC_PROV[pid]
        if not p:
            # Keep the last good copy of this province rather than wiping it.
            old = next((x for x in (prev or {}).get("prov", []) if x.get("id") == pid), None)
            if old:
                data["prov"].append(old)
                for code in old.get("munis", []):
                    if code in prev["munis"]:
                        data["munis"][code] = prev["munis"][code]
                        used.update(r[0] for r in prev["munis"][code]["res"])
                        used.update(w[0] for w in prev["munis"][code]["wards"].values())
                failed.append(key)
            else:
                data["prov"].append({"id": pid, "code": key, "prog": None, "res": [], "munis": []})
            continue
        codes = []
        all_wards = []
        for m in p.get("MunicipalityResults", []):
            code, _, name = m.get("Municipality", "").partition(" - ")
            code = code.strip()
            codes.append(code)
            pre = ward_prefix(code)
            if pre:
                prefix_to_code[pre] = code
            data["munis"][code] = {
                "name": name.strip() or code, "prov": key, "prog": prog(m),
                "turnout": turnout(m.get("PartyBallotResults")),
                "res": results(m.get("PartyBallotResults"), used), "wards": {},
                "mid": m.get("MunicipalityID"),
            }
            all_wards.extend(m.get("WardResults", []))
        # The IEC province file lists every ward under one municipality, so assign
        # wards by the municipality code embedded in the ward ID.
        for w in all_wards:
            wid = str(w.get("WardID", ""))
            code = prefix_to_code.get(wid[:5])
            lead = next((b for b in w.get("PartyBallotResults", []) if b.get("IsLeadingPartyVotes") or b.get("IsLeadingParty")), None)
            if not code or code not in data["munis"] or not lead:
                continue
            used.add(lead["ID"])
            data["munis"][code]["wards"][str(int(wid[-3:]))] = [lead["ID"], lead.get("PercOfVotes", 0), 1 if lead.get("TotalSeatsWon") else 0]
        data["prov"].append({"id": pid, "code": key, "name": p.get("Province"), "prog": prog(p),
                             "turnout": turnout(p.get("PartyBallotResults")),
                             "res": results(p.get("PartyBallotResults"), used), "munis": codes})

    fetch_full(base, data, prev, used)

    data["parties"] = {str(i): [pmeta[i]["Name"], pmeta[i]["PartyFullName"].title(), pmeta[i]["sWebColour"]]
                       for i in sorted(used) if i in pmeta}
    for k, v in ((prev or {}).get("parties") or {}).items():
        if int(k) in used:
            data["parties"].setdefault(k, v)

    if failed:
        print(f"warn: kept previous data for {', '.join(failed)}", file=sys.stderr)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # Skip rewriting when nothing but the fetch time changed, so we don't commit noise.
    try:
        old = json.load(open(out))
        if {k: v for k, v in old.items() if k != "fetched"} == {k: v for k, v in data.items() if k != "fetched"}:
            print("unchanged")
            return
    except (OSError, ValueError):
        pass
    with open(out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    wards = sum(len(m["wards"]) for m in data["munis"].values())
    print(f"wrote {out}: {len(data['munis'])} councils, {wards} wards, {os.path.getsize(out)//1024} KB")


if __name__ == "__main__":
    main()
