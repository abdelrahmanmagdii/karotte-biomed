"""The cohort data, its answer, and the mistakes that must get it wrong."""

import datetime as dt
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from environment.tasks.cohort_query import data
from environment.tasks.cohort_query.reference_solution import solve

SEEDS = (0, 1, 2)
REFERENCE = Path(data.__file__).parent / "reference_solution.py"

# Each is a plausible slip by a solution that reads the data carefully but not
# carefully enough; each must change the count on its own.
MISTAKES = (
    "drop_null_results",  # Skips results stored only as ">14.0".
    "no_merge",  # Counts PATIDs instead of people.
    "type1_icd10_only",  # Misses type 1 diabetes coded in ICD-9.
    "exclude_all_icd9_diabetes",  # Treats every 250.xx as type 1.
    "washout_includes_index",  # Lets the index visit itself satisfy the washout.
    "no_washout",
    "ignore_units",
    "any_e11_date",
    "any_loinc",
    "age_today",
)


@pytest.fixture(params=SEEDS, scope="module")
def run(request, tmp_path_factory):
    seed = request.param
    patients = data.generate(seed)
    db = tmp_path_factory.mktemp(f"seed{seed}") / "cohort.db"
    db.write_bytes(data.to_sqlite(patients, seed))
    return db, sum(data.in_cohort(p) for p in patients)


def test_the_reference_solution_finds_the_answer(run):
    db, expected = run
    assert solve(str(db)) == expected


def test_the_reference_solution_runs_as_a_script(run):
    db, expected = run
    out = subprocess.run(
        [sys.executable, "-I", str(REFERENCE), str(db)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == str(expected)


def test_the_answer_is_not_trivial(run):
    _, expected = run
    assert 50 < expected < 500


def test_generation_is_deterministic():
    assert data.to_sqlite(data.generate(7), 7) == data.to_sqlite(data.generate(7), 7)
    assert data.to_sqlite(data.generate(7), 7) != data.to_sqlite(data.generate(8), 8)


def test_the_data_has_every_trap():
    patients = data.generate(0)
    con = sqlite3.connect(":memory:")
    con.deserialize(data.to_sqlite(patients, 0))

    def values(sql: str) -> set:
        return {row[0] for row in con.execute(sql)}

    assert {"E11.9", "E119"} <= values("SELECT DX FROM DIAGNOSIS")
    icd9 = values("SELECT REPLACE(DX, '.', '') FROM DIAGNOSIS WHERE DX_TYPE = '09'")
    assert icd9 & {"25000", "25002"} and icd9 & {"25001", "25003"}
    assert {"%", "mmol/mol", "mg/dL"} <= values("SELECT RESULT_UNIT FROM LAB_RESULT_CM")
    assert {"GT", "NI"} <= values(
        "SELECT RESULT_MODIFIER FROM LAB_RESULT_CM WHERE RESULT_NUM IS NULL"
    )
    assert values("SELECT COUNT(*) FROM PATID_MERGE") != {0}


def test_hba1c_values_stay_clear_of_the_threshold():
    for p in data.generate(0):
        for lab in p.labs:
            if lab.loinc in data.HBA1C_LOINCS and lab.value is not None:
                assert (
                    abs(lab.value - data.THRESHOLD_PERCENT) >= data.THRESHOLD_GAP - 1e-9
                )


@pytest.mark.parametrize("mistake", MISTAKES)
def test_each_mistake_gets_a_different_answer(run, mistake):
    db, expected = run
    assert _count(db, mistake) != expected


def test_the_mistake_counter_without_a_mistake_is_right(run):
    db, expected = run
    assert _count(db, None) == expected


def _count(db: Path, mistake: str | None) -> int:
    """The criteria written another way, with one mistake switched on."""
    con = sqlite3.connect(db)
    merged = (
        {}
        if mistake == "no_merge"
        else dict(con.execute("SELECT RETIRED_PATID, SURVIVING_PATID FROM PATID_MERGE"))
    )

    def who(patid: str) -> str:
        return merged.get(patid, patid)

    births = {
        who(p): dt.date.fromisoformat(b)
        for p, b in con.execute("SELECT PATID, BIRTH_DATE FROM DEMOGRAPHIC")
    }
    t2d: dict[str, list[dt.date]] = {}
    excluded: set[str] = set()
    for patid, dx, dx_type, day in con.execute(
        "SELECT PATID, REPLACE(DX, '.', ''), DX_TYPE, ADMIT_DATE FROM DIAGNOSIS"
    ):
        if dx_type == "10" and dx.startswith("E11"):
            t2d.setdefault(who(patid), []).append(dt.date.fromisoformat(day))
        icd9_type1 = dx.startswith("250") and (
            mistake == "exclude_all_icd9_diabetes" or dx[-1] in "13"
        )
        if (dx_type == "10" and dx.startswith("E10")) or (
            dx_type == "09" and icd9_type1 and mistake != "type1_icd10_only"
        ):
            excluded.add(who(patid))

    visits: dict[str, list[dt.date]] = {}
    for patid, day in con.execute("SELECT PATID, ADMIT_DATE FROM ENCOUNTER"):
        visits.setdefault(who(patid), []).append(dt.date.fromisoformat(day))

    loinc = "" if mistake == "any_loinc" else "AND LAB_LOINC IN ('4548-4', '17856-6')"
    null = "AND RESULT_NUM IS NOT NULL" if mistake == "drop_null_results" else ""
    cohort = set()
    for patid, value, unit, modifier, day in con.execute(
        "SELECT PATID, RESULT_NUM, RESULT_UNIT, RESULT_MODIFIER, RESULT_DATE"
        f" FROM LAB_RESULT_CM WHERE RESULT_MODIFIER != 'NI' {loinc} {null}"
    ):
        person = who(patid)
        if person not in t2d or person in excluded:
            continue
        index = min(t2d[person])
        indexes = t2d[person] if mistake == "any_e11_date" else [index]
        age_day = dt.date(2026, 1, 1) if mistake == "age_today" else index
        if data.age_on(births[person], age_day) < data.MIN_AGE:
            continue
        first_day = 0 if mistake == "washout_includes_index" else 1
        if mistake != "no_washout" and not any(
            first_day <= (index - v).days <= data.WASHOUT_DAYS
            for v in visits.get(person, ())
        ):
            continue
        if modifier == "GT":
            percent = data.REPORTABLE_MAX + 0.1
        elif mistake == "ignore_units" or unit != "mmol/mol":
            percent = value
        else:
            percent = 0.09148 * value + 2.152
        lab_day = dt.date.fromisoformat(day)
        if percent > 9.0 and any(0 <= (lab_day - i).days <= 90 for i in indexes):
            cohort.add(person)
    return len(cohort)
