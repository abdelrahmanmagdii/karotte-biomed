"""A correct solution that reads only what the student sees. Standard library
only, so it runs as the student:
`python reference_solution.py <data dir> <generic drug> <reaction term>`."""

import csv
import sys
from pathlib import Path


def solve(data_dir: str, drug: str, event: str) -> str:
    root = Path(data_dir)

    def rows(name: str) -> list[dict[str, str]]:
        with open(root / name, newline="") as f:
            return list(csv.DictReader(f))

    ingredients = {
        r["drugname"].strip().upper(): {
            i.strip().upper() for i in r["prod_ai"].split("\\")
        }
        for r in rows("drug_dictionary.csv")
    }
    preferred = {
        r["llt"].strip().lower(): r["pt"].strip().lower() for r in rows("meddra.csv")
    }
    deleted = {r["caseid"].strip() for r in rows("deleted_cases.csv")}

    # 1. The latest version of each case.
    latest: dict[str, dict[str, str]] = {}
    for r in rows("reports.csv"):
        if r["caseid"] not in latest or int(r["caseversion"]) > int(
            latest[r["caseid"]]["caseversion"]
        ):
            latest[r["caseid"]] = r
    # 2. Without the deleted cases.
    cases = [r for caseid, r in latest.items() if caseid not in deleted]
    # 3. One case per patient, when the patient can be identified.
    newest: dict[tuple[str, ...], dict[str, str]] = {}
    for r in cases:
        if r["age"] and r["event_dt"]:
            key = (r["age"], r["sex"], r["occr_country"], r["event_dt"])
            if key not in newest or r["fda_dt"] > newest[key]["fda_dt"]:
                newest[key] = r
    keep = {
        r["primaryid"]
        for r in cases
        if not (r["age"] and r["event_dt"])
        or newest[(r["age"], r["sex"], r["occr_country"], r["event_dt"])] is r
    }

    exposed = {
        r["primaryid"]
        for r in rows("drugs.csv")
        if r["primaryid"] in keep
        and r["role_cod"] == "PS"
        and drug.upper() in ingredients.get(r["drugname"].strip().upper(), ())
    }
    with_reactions: set[str] = set()
    with_event: set[str] = set()
    for r in rows("reactions.csv"):
        if r["primaryid"] in keep:
            # 4. Only cases that list a reaction count, by preferred term.
            with_reactions.add(r["primaryid"])
            if preferred[r["pt"].strip().lower()] == event.lower():
                with_event.add(r["primaryid"])

    exposed &= with_reactions
    a = len(exposed & with_event)
    b = len(exposed - with_event)
    c = len(with_event - exposed)
    d = len(with_reactions - exposed - with_event)
    return f"{(a / (a + b)) / (c / (c + d)):.2f}"


if __name__ == "__main__":
    print(solve(sys.argv[1], sys.argv[2], sys.argv[3]))
