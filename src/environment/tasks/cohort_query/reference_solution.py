"""A correct solution that reads only what the student sees. Standard library
only, so it runs as the student: `python reference_solution.py <cohort.db>`."""

import datetime as dt
import sqlite3
import sys

HBA1C_LOINCS = ("4548-4", "17856-6")


def solve(db_path: str) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    merged = dict(con.execute("SELECT RETIRED_PATID, SURVIVING_PATID FROM PATID_MERGE"))

    def person(patid: str) -> str:
        while patid in merged:
            patid = merged[patid]
        return patid

    births = {
        person(p): dt.date.fromisoformat(b)
        for p, b in con.execute("SELECT PATID, BIRTH_DATE FROM DEMOGRAPHIC")
    }
    index: dict[str, dt.date] = {}
    type1: set[str] = set()
    for patid, dx, dx_type, day in con.execute(
        "SELECT PATID, DX, DX_TYPE, ADMIT_DATE FROM DIAGNOSIS"
    ):
        who, code = person(patid), dx.strip().upper().replace(".", "")
        if dx_type == "10" and code.startswith("E11"):
            date = dt.date.fromisoformat(day)
            index[who] = min(index.get(who, date), date)
        if (dx_type == "10" and code.startswith("E10")) or (
            dx_type == "09" and code.startswith("250") and code[-1] in "13"
        ):
            type1.add(who)

    visits: dict[str, list[dt.date]] = {}
    for patid, day in con.execute("SELECT PATID, ADMIT_DATE FROM ENCOUNTER"):
        visits.setdefault(person(patid), []).append(dt.date.fromisoformat(day))

    high: dict[str, list[dt.date]] = {}
    for patid, num, unit, modifier, raw, day in con.execute(
        "SELECT PATID, RESULT_NUM, RESULT_UNIT, RESULT_MODIFIER, RAW_RESULT, RESULT_DATE"
        " FROM LAB_RESULT_CM WHERE LAB_LOINC IN (?, ?)",
        HBA1C_LOINCS,
    ):
        if num is None:
            # Above the analyzer's range: the bound is only in the raw text.
            if modifier != "GT":
                continue  # Cancelled.
            num = float(raw.strip().lstrip(">").split()[0])
        percent = 0.09148 * num + 2.152 if unit == "mmol/mol" else num
        if percent > 9.0 or (modifier == "GT" and percent >= 9.0):
            high.setdefault(person(patid), []).append(dt.date.fromisoformat(day))

    count = 0
    for who, start in index.items():
        birth = births[who]
        age = (
            start.year
            - birth.year
            - ((start.month, start.day) < (birth.month, birth.day))
        )
        if (
            who not in type1
            and age >= 65
            and any(1 <= (start - v).days <= 365 for v in visits.get(who, ()))
            and any(0 <= (d - start).days <= 90 for d in high.get(who, ()))
        ):
            count += 1
    return count


if __name__ == "__main__":
    print(solve(sys.argv[1]))
