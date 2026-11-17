"""Synthetic patients in a subset of the PCORnet Common Data Model.

Each person is first built as clean Python objects, and the answer is counted
from those. Only then are they written to SQLite the way real clinical data
looks: codes with and without the dot, HbA1c in two units, duplicate rows,
cancelled results, results above the analyzer's range stored only as text, and
people registered under two PATIDs. A solution has to handle all of that to
match the count.
"""

import datetime as dt
import random
import sqlite3
from dataclasses import dataclass, field

HBA1C_LOINCS = ("4548-4", "17856-6")
GLUCOSE_LOINC = "2345-7"
T2D_CODES = ("E11.9", "E11.65", "E11.22", "E11.40", "E11.8", "E11.21")
T1D_CODES = ("E10.9", "E10.65", "E10.10")
OTHER_DIABETES_CODES = ("E10.9", "E13.9", "R73.03", "O24.410")
NOISE_CODES = ("I10", "E78.5", "Z83.3", "N18.3", "J45.909")
# ICD-9-CM 250.xy: a fifth digit y of 0 or 2 is type 2, 1 or 3 is type 1.
# Used before ICD-10 took over on 2015-10-01.
ICD9_T2D_CODES = ("250.00", "250.02", "250.40")
ICD9_T1D_CODES = ("250.01", "250.03", "250.41", "250.13")
ENCOUNTER_TYPES = ("AV", "AV", "AV", "IP", "ED", "TH")

MIN_AGE = 65
WINDOW_DAYS = 90
WASHOUT_DAYS = 365
THRESHOLD_PERCENT = 9.0
# No generated HbA1c lies closer to the threshold than this, so rounding the
# mmol/mol values or using a slightly different conversion can't flip a result.
THRESHOLD_GAP = 0.2
# The analyzer reports anything higher as ">14.0" with no number.
REPORTABLE_MAX = 14.0

DEFAULT_PATIENTS = 2000


@dataclass
class Diagnosis:
    code: str  # Canonical, with the dot.
    dx_type: str  # "10" for ICD-10-CM, "09" for ICD-9-CM.
    date: dt.date


@dataclass
class Lab:
    loinc: str
    value: float | None  # HbA1c in % (NGSP), glucose in mg/dL; None if cancelled.
    date: dt.date


@dataclass
class Patient:
    patid: str
    birth_date: dt.date
    sex: str
    diagnoses: list[Diagnosis] = field(default_factory=list)
    labs: list[Lab] = field(default_factory=list)
    encounters: list[dt.date] = field(default_factory=list)
    # A second PATID the same person was registered under, since merged into
    # `patid`. Some of their rows are stored under it.
    alias: str | None = None


def age_on(birth: dt.date, day: dt.date) -> int:
    """Completed years."""
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


def is_type1(d: Diagnosis) -> bool:
    if d.dx_type == "10":
        return d.code.startswith("E10")
    return d.code.startswith("250") and d.code[-1] in "13"


def in_cohort(patient: Patient) -> bool:
    """The question the task asks, answered on the clean model."""
    t2d = [
        d.date
        for d in patient.diagnoses
        if d.dx_type == "10" and d.code.startswith("E11")
    ]
    if not t2d or any(is_type1(d) for d in patient.diagnoses):
        return False
    index = min(t2d)
    if age_on(patient.birth_date, index) < MIN_AGE:
        return False
    if not any(1 <= (index - e).days <= WASHOUT_DAYS for e in patient.encounters):
        return False
    return any(
        lab.loinc in HBA1C_LOINCS
        and lab.value is not None
        and lab.value > THRESHOLD_PERCENT
        and 0 <= (lab.date - index).days <= WINDOW_DAYS
        for lab in patient.labs
    )


def generate(seed: int, n_patients: int = DEFAULT_PATIENTS) -> list[Patient]:
    rng = random.Random(seed)
    ids = [f"P{i}" for i in rng.sample(range(10_000_000, 99_999_999), 2 * n_patients)]
    patients = [_patient(rng, patid) for patid in ids[:n_patients]]
    spare = iter(ids[n_patients:])
    for p in patients:
        # People with diabetes see more providers, so get registered twice more.
        if rng.random() < (0.15 if p.diagnoses else 0.05):
            p.alias = next(spare)
    return patients


def to_sqlite(patients: list[Patient], seed: int) -> bytes:
    """The patients as a SQLite database, in the messy form the student sees."""
    rng = random.Random(seed ^ 0x5EED)
    demographic, merges, diagnosis, labs, encounters = [], [], [], [], []
    for p in patients:

        def owner(p: Patient = p) -> str:
            return p.alias if p.alias and rng.random() < 0.4 else p.patid

        demographic.append((p.patid, p.birth_date.isoformat(), p.sex))
        if p.alias:
            demographic.append((p.alias, p.birth_date.isoformat(), p.sex))
            merged = _random_date(rng, dt.date(2018, 1, 1), dt.date(2025, 6, 28))
            merges.append((p.alias, p.patid, merged.isoformat()))
        for d in p.diagnoses:
            code = d.code.replace(".", "") if rng.random() < 0.5 else d.code
            row = (owner(), code, d.dx_type, d.date.isoformat())
            diagnosis.extend([row] * (2 if rng.random() < 0.05 else 1))
        for lab in p.labs:
            row = _lab_row(rng, owner(), lab)
            labs.extend([row] * (2 if rng.random() < 0.05 else 1))
        for day in p.encounters:
            encounters.append((owner(), day.isoformat(), rng.choice(ENCOUNTER_TYPES)))
    for rows in (demographic, diagnosis, labs, encounters):
        rng.shuffle(rows)

    con = sqlite3.connect(":memory:")
    con.executescript(_SCHEMA)
    con.executemany("INSERT INTO DEMOGRAPHIC VALUES (?, ?, ?)", demographic)
    con.executemany("INSERT INTO PATID_MERGE VALUES (?, ?, ?)", merges)
    con.executemany(
        "INSERT INTO DIAGNOSIS (PATID, DX, DX_TYPE, ADMIT_DATE) VALUES (?, ?, ?, ?)",
        diagnosis,
    )
    con.executemany(
        "INSERT INTO LAB_RESULT_CM (PATID, LAB_LOINC, RESULT_NUM, RESULT_UNIT,"
        " RESULT_MODIFIER, RAW_RESULT, RESULT_DATE) VALUES (?, ?, ?, ?, ?, ?, ?)",
        labs,
    )
    con.executemany(
        "INSERT INTO ENCOUNTER (PATID, ADMIT_DATE, ENC_TYPE) VALUES (?, ?, ?)",
        encounters,
    )
    con.commit()
    data = con.serialize()
    con.close()
    return data


_SCHEMA = """
CREATE TABLE DEMOGRAPHIC (PATID TEXT PRIMARY KEY, BIRTH_DATE TEXT, SEX TEXT);
CREATE TABLE PATID_MERGE (
    RETIRED_PATID TEXT PRIMARY KEY, SURVIVING_PATID TEXT, MERGE_DATE TEXT
);
CREATE TABLE ENCOUNTER (
    ENCOUNTERID INTEGER PRIMARY KEY, PATID TEXT, ADMIT_DATE TEXT, ENC_TYPE TEXT
);
CREATE TABLE DIAGNOSIS (
    DIAGNOSISID INTEGER PRIMARY KEY, PATID TEXT, DX TEXT, DX_TYPE TEXT, ADMIT_DATE TEXT
);
CREATE TABLE LAB_RESULT_CM (
    LAB_RESULT_CM_ID INTEGER PRIMARY KEY, PATID TEXT, LAB_LOINC TEXT,
    RESULT_NUM REAL, RESULT_UNIT TEXT, RESULT_MODIFIER TEXT, RAW_RESULT TEXT,
    RESULT_DATE TEXT
);
"""


def _lab_row(rng: random.Random, patid: str, lab: Lab) -> tuple:
    day = lab.date.isoformat()
    if lab.loinc == GLUCOSE_LOINC:
        return (patid, lab.loinc, lab.value, "mg/dL", "EQ", f"{lab.value:g}", day)
    if lab.value is None:
        return (patid, lab.loinc, None, "%", "NI", "CANCELLED", day)
    if lab.value > REPORTABLE_MAX:
        return (patid, lab.loinc, None, "%", "GT", f">{REPORTABLE_MAX:.1f}", day)
    if rng.random() < 0.3:
        # IFCC units; NGSP % = 0.09148 * mmol/mol + 2.152.
        mmol = float(round((lab.value - 2.152) / 0.09148))
        return (patid, lab.loinc, mmol, "mmol/mol", "EQ", f"{mmol:g}", day)
    return (patid, lab.loinc, lab.value, "%", "EQ", f"{lab.value:g}", day)


def _patient(rng: random.Random, patid: str) -> Patient:
    birth = dt.date(rng.randint(1925, 1975), rng.randint(1, 12), rng.randint(1, 28))
    p = Patient(patid=patid, birth_date=birth, sex=rng.choice("FM"))
    kind = rng.random()
    if kind < 0.5:
        _add_t2d(rng, p)
    elif kind < 0.65:
        # Other diabetes types, often with high HbA1c, which must not count.
        day = _random_date(rng, dt.date(2016, 1, 1), dt.date(2024, 6, 28))
        p.diagnoses.append(Diagnosis(rng.choice(OTHER_DIABETES_CODES), "10", day))
        for _ in range(rng.randint(0, 3)):
            p.labs.append(
                Lab(rng.choice(HBA1C_LOINCS), _hba1c(rng), day + _days(rng, -30, 120))
            )
    for _ in range(rng.randint(0, 3)):
        day = _random_date(rng, dt.date(2016, 1, 1), dt.date(2024, 12, 28))
        p.diagnoses.append(Diagnosis(rng.choice(NOISE_CODES), "10", day))
    for _ in range(rng.randint(0, 3)):
        day = _random_date(rng, dt.date(2016, 1, 1), dt.date(2024, 12, 28))
        p.labs.append(Lab(GLUCOSE_LOINC, float(rng.randint(70, 340)), day))
    # Every diagnosis was made at a visit, plus some visits without one.
    p.encounters.extend(d.date for d in p.diagnoses)
    for _ in range(rng.randint(0, 3)):
        p.encounters.append(
            _random_date(rng, dt.date(2015, 1, 1), dt.date(2024, 12, 28))
        )
    return p


def _add_t2d(rng: random.Random, p: Patient) -> None:
    index = _random_date(rng, dt.date(2016, 1, 1), dt.date(2024, 6, 28))
    edge = rng.random()
    if edge < 0.12:  # Turns 65 on the index date: counts.
        p.birth_date = index.replace(year=index.year - MIN_AGE)
    elif edge < 0.24:  # Turns 65 the day after: doesn't.
        p.birth_date = index.replace(year=index.year - MIN_AGE) + dt.timedelta(days=1)

    p.diagnoses.append(Diagnosis(rng.choice(T2D_CODES), "10", index))
    later: list[dt.date] = []
    for _ in range(rng.randint(0, 2)):
        day = index + _days(rng, 150, 900)
        later.append(day)
        p.diagnoses.append(Diagnosis(rng.choice(T2D_CODES), "10", day))

    old = _random_date(rng, dt.date(2010, 1, 1), dt.date(2015, 9, 30))
    history = rng.random()
    if history < 0.2:  # A type 2 code from the ICD-9 era: neither index nor exclusion.
        p.diagnoses.append(Diagnosis(rng.choice(ICD9_T2D_CODES), "09", old))
    elif history < 0.28:  # Type 1 in the ICD-9 era: excluded.
        p.diagnoses.append(Diagnosis(rng.choice(ICD9_T1D_CODES), "09", old))
    elif history < 0.34:  # A type 1 code at some point: excluded.
        day = index + _days(rng, -400, 900)
        p.diagnoses.append(Diagnosis(rng.choice(T1D_CODES), "10", day))

    # Earlier visits; only those 1 to 365 days before the index date count.
    for _ in range(rng.choice((0, 1, 1, 2))):
        before = rng.choice((1, 30, 200, 365, 365, 366, 366, 400, 700))
        p.encounters.append(index - dt.timedelta(days=before))

    offsets = [-60, -1, 0, 1, 45, 89, 90, 91, 120, 365]
    for _ in range(rng.randint(0, 4)):
        if later and rng.random() < 0.25:
            # Near a later diagnosis, outside the index window.
            day = rng.choice(later) + _days(rng, 0, 30)
        else:
            day = index + dt.timedelta(days=rng.choice(offsets))
        value = None if rng.random() < 0.05 else _hba1c(rng)
        p.labs.append(Lab(rng.choice(HBA1C_LOINCS), value, day))


def _hba1c(rng: random.Random) -> float:
    r = rng.random()
    if r < 0.45:
        return round(rng.uniform(5.2, THRESHOLD_PERCENT - THRESHOLD_GAP), 1)
    if r < 0.8:
        return round(rng.uniform(THRESHOLD_PERCENT + THRESHOLD_GAP, REPORTABLE_MAX), 1)
    return round(rng.uniform(REPORTABLE_MAX + 0.1, 17.5), 1)


def _random_date(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    day = start + dt.timedelta(days=rng.randint(0, (end - start).days))
    return day.replace(day=min(day.day, 28))


def _days(rng: random.Random, low: int, high: int) -> dt.timedelta:
    return dt.timedelta(days=rng.randint(low, high))
