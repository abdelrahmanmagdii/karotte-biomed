"""Synthetic spontaneous adverse-event reports, laid out like FDA's FAERS
quarterly files.

Each case is first built as clean Python objects, and the PRR is computed from
those. The CSVs the student sees then carry the usual problems: several
versions of a case, cases FDA later deleted, the same patient reported twice
under different case ids, brand, salt and combination product names, the drug
listed only as concomitant, reactions coded as MedDRA lowest level terms, and
cases without any reaction.

The drug names are real; the MedDRA-style term hierarchy is a small synthetic
stand-in, not MedDRA itself.
"""

import csv
import datetime as dt
import io
import random
from dataclasses import dataclass, field
from fractions import Fraction

# Drug-event pairs with a known safety signal.
SIGNALS = {
    "metformin": "Lactic acidosis",
    "atorvastatin": "Rhabdomyolysis",
    "lisinopril": "Angioedema",
    "warfarin": "Haemorrhage",
    "amiodarone": "Pulmonary fibrosis",
}
# The drugs a run asks about: each is also sold in a combination product.
ASKED = ("metformin", "atorvastatin", "lisinopril")

# Product name -> active ingredients.
PRODUCTS: dict[str, tuple[str, ...]] = {
    "METFORMIN": ("metformin",),
    "METFORMIN HYDROCHLORIDE": ("metformin",),
    "GLUCOPHAGE": ("metformin",),
    "FORTAMET": ("metformin",),
    "JANUMET": ("sitagliptin", "metformin"),
    "SYNJARDY": ("empagliflozin", "metformin"),
    "JANUVIA": ("sitagliptin",),
    "JARDIANCE": ("empagliflozin",),
    "ATORVASTATIN": ("atorvastatin",),
    "ATORVASTATIN CALCIUM": ("atorvastatin",),
    "LIPITOR": ("atorvastatin",),
    "CADUET": ("amlodipine", "atorvastatin"),
    "NORVASC": ("amlodipine",),
    "LISINOPRIL": ("lisinopril",),
    "ZESTRIL": ("lisinopril",),
    "PRINIVIL": ("lisinopril",),
    "ZESTORETIC": ("lisinopril", "hydrochlorothiazide"),
    "MICROZIDE": ("hydrochlorothiazide",),
    "WARFARIN": ("warfarin",),
    "WARFARIN SODIUM": ("warfarin",),
    "COUMADIN": ("warfarin",),
    "AMIODARONE": ("amiodarone",),
    "AMIODARONE HCL": ("amiodarone",),
    "PACERONE": ("amiodarone",),
    "IBUPROFEN": ("ibuprofen",),
    "ADVIL": ("ibuprofen",),
    "OMEPRAZOLE": ("omeprazole",),
    "PRILOSEC": ("omeprazole",),
    "SERTRALINE": ("sertraline",),
    "ZOLOFT": ("sertraline",),
    "SYNTHROID": ("levothyroxine",),
}

# Preferred term -> lowest level terms that map to it besides itself.
TERMS: dict[str, tuple[str, ...]] = {
    "Lactic acidosis": ("Acidosis lactic", "Lactic acidosis aggravated"),
    "Rhabdomyolysis": ("Muscle breakdown", "Rhabdomyolysis acute"),
    "Angioedema": ("Angioneurotic oedema", "Quincke's oedema"),
    "Haemorrhage": ("Hemorrhage", "Bleeding"),
    "Pulmonary fibrosis": ("Lung fibrosis", "Fibrosis pulmonary"),
    "Nausea": ("Feeling sick",),
    "Headache": ("Head pain",),
    "Dizziness": ("Giddiness",),
    "Fatigue": ("Tiredness",),
    "Rash": ("Skin rash",),
    "Diarrhoea": ("Diarrhea",),
    "Vomiting": ("Emesis",),
    "Dyspnoea": ("Shortness of breath",),
    "Pruritus": ("Itching",),
    "Arthralgia": ("Joint pain",),
}
BACKGROUND_EVENTS = tuple(t for t in TERMS if t not in SIGNALS.values())
COUNTRIES = ("US", "US", "US", "GB", "DE", "FR", "JP", "CA", "IT", "ES")

DEFAULT_CASES = 3000


@dataclass
class Version:
    fda_dt: dt.date
    drugs: list[tuple[str, str]] = field(default_factory=list)  # (product, role)
    reactions: list[str] = field(default_factory=list)  # Preferred terms.


@dataclass
class Case:
    caseid: int
    age: int | None
    sex: str
    country: str
    event_dt: dt.date | None
    versions: list[Version]  # Oldest first; only the last one counts.

    @property
    def patient(self) -> tuple | None:
        """What identifies the patient, if enough of it is known."""
        if self.age is None or self.event_dt is None:
            return None
        return (self.age, self.sex, self.country, self.event_dt)


@dataclass
class Dataset:
    drug: str
    event: str
    cases: list[Case]
    deleted: set[int]


def counted_cases(ds: Dataset) -> list[Case]:
    """The cases the PRR counts, by the task's rules in their order."""
    kept = [c for c in ds.cases if c.caseid not in ds.deleted]
    latest: dict[tuple, Case] = {}
    for c in kept:
        if (key := c.patient) is not None and (
            key not in latest or c.versions[-1].fda_dt > latest[key].versions[-1].fda_dt
        ):
            latest[key] = c
    kept = [c for c in kept if c.patient is None or latest[c.patient] is c]
    return [c for c in kept if c.versions[-1].reactions]


def contingency(ds: Dataset) -> tuple[int, int, int, int]:
    """a: drug and event, b: drug without event, c: event without drug,
    d: neither."""
    a = b = c = d = 0
    for case in counted_cases(ds):
        latest = case.versions[-1]
        exposed = any(
            ds.drug in PRODUCTS[product] and role == "PS"
            for product, role in latest.drugs
        )
        event = ds.event in latest.reactions
        if exposed and event:
            a += 1
        elif exposed:
            b += 1
        elif event:
            c += 1
        else:
            d += 1
    return a, b, c, d


def prr(ds: Dataset) -> Fraction:
    a, b, c, d = contingency(ds)
    return Fraction(a, a + b) / Fraction(c, c + d)


def expected_answer(ds: Dataset) -> str:
    return f"{float(prr(ds)):.2f}"


def generate(seed: int, n_cases: int = DEFAULT_CASES) -> Dataset:
    """A dataset whose PRR is well defined and not close to a rounding edge,
    so the two-decimal answer is unambiguous."""
    rng = random.Random(seed)
    while True:
        ds = _dataset(rng, n_cases)
        a, b, c, d = contingency(ds)
        if min(a, b, c, d) == 0:
            continue
        hundredths = prr(ds) * 100
        if abs(hundredths - int(hundredths) - Fraction(1, 2)) > Fraction(1, 100):
            return ds


def to_csv(ds: Dataset, seed: int) -> dict[str, bytes]:
    """The dataset as the CSV files the student sees."""
    rng = random.Random(seed ^ 0xFAE5)
    reports, drugs, reactions = [], [], []
    for case in ds.cases:
        for number, version in enumerate(case.versions, start=1):
            primaryid = f"{case.caseid}{number}"
            reports.append(
                (
                    primaryid,
                    case.caseid,
                    number,
                    _yyyymmdd(version.fda_dt),
                    _yyyymmdd(case.event_dt),
                    "" if case.age is None else case.age,
                    case.sex,
                    case.country,
                )
            )
            for seq, (product, role) in enumerate(version.drugs, start=1):
                drugs.append((primaryid, seq, _messy(rng, product), role))
            for pt in version.reactions:
                term = rng.choice(TERMS[pt]) if rng.random() < 0.3 else pt
                reactions.append((primaryid, _messy_term(rng, term)))
    for rows in (reports, drugs, reactions):
        rng.shuffle(rows)
    dictionary = [
        (name, "\\".join(i.upper() for i in ingredients))
        for name, ingredients in sorted(PRODUCTS.items())
    ]
    meddra = sorted((llt, pt) for pt, llts in TERMS.items() for llt in (pt, *llts))
    # FDA's list covers all of FAERS, not just this extract.
    deleted = sorted(ds.deleted | set(rng.sample(range(10_000_000, 99_999_999), 25)))
    return {
        "reports.csv": _csv(
            (
                "primaryid",
                "caseid",
                "caseversion",
                "fda_dt",
                "event_dt",
                "age",
                "sex",
                "occr_country",
            ),
            reports,
        ),  # fmt: skip
        "drugs.csv": _csv(("primaryid", "drug_seq", "drugname", "role_cod"), drugs),
        "reactions.csv": _csv(("primaryid", "pt"), reactions),
        "drug_dictionary.csv": _csv(("drugname", "prod_ai"), dictionary),
        "meddra.csv": _csv(("llt", "pt"), meddra),
        "deleted_cases.csv": _csv(("caseid",), [(c,) for c in deleted]),
    }


def _dataset(rng: random.Random, n_cases: int) -> Dataset:
    drug = rng.choice(ASKED)
    event = SIGNALS[drug]
    with_drug = sorted(p for p, ing in PRODUCTS.items() if drug in ing)
    combos = [p for p in with_drug if len(PRODUCTS[p]) > 1]
    singles = [p for p in with_drug if len(PRODUCTS[p]) == 1]
    without = sorted(p for p, ing in PRODUCTS.items() if drug not in ing)
    events = [*BACKGROUND_EVENTS, *(e for e in SIGNALS.values() if e != event)]
    exposure = rng.uniform(0.08, 0.15)
    rate_exposed, rate_other = rng.uniform(0.08, 0.2), rng.uniform(0.01, 0.03)

    ids = iter(rng.sample(range(10_000_000, 99_999_999), 2 * n_cases))
    patients: set[tuple] = set()
    cases: list[Case] = []
    deleted: set[int] = set()
    for _ in range(n_cases):
        exposed = rng.random() < exposure
        final = Version(_random_date(rng, dt.date(2024, 6, 1), dt.date(2025, 9, 30)))
        suspect = rng.choice(
            (combos if rng.random() < 0.3 else singles) if exposed else without
        )
        final.drugs.append((suspect, "PS"))
        for other in rng.sample(without, rng.randint(0, 3)):
            if all(other != p for p, _ in final.drugs):
                final.drugs.append((other, rng.choice(("SS", "C"))))
        if not exposed and rng.random() < 0.1:
            # Taken, but not the suspect.
            final.drugs.append((rng.choice(with_drug), rng.choice(("SS", "C"))))
        final.reactions = rng.sample(events, rng.randint(1, 3))
        if rng.random() < (rate_exposed if exposed else rate_other):
            final.reactions.append(event)
        if rng.random() < (0.15 if exposed else 0.04):
            # A follow-up that withdrew every reaction, common in reports from
            # manufacturer patient-support programs about their own product.
            final.reactions = []

        case = _case(rng, next(ids), final, drug, event, patients)
        cases.append(case)
        # FDA deletes erroneous and duplicate reports, which cluster around a
        # publicized drug-event pair.
        reported = event in final.reactions
        if rng.random() < (0.3 if exposed and reported else 0.03 if reported else 0.01):
            deleted.add(case.caseid)
        if case.patient is not None and rng.random() < (0.25 if exposed else 0.04):
            cases.append(_duplicate(rng, next(ids), case, drug, event, with_drug))
    rng.shuffle(cases)
    return Dataset(drug, event, cases, deleted)


def _case(
    rng: random.Random,
    caseid: int,
    final: Version,
    drug: str,
    event: str,
    patients: set[tuple],
) -> Case:
    while True:
        age = None if rng.random() < 0.15 else rng.randint(18, 90)
        known = rng.random() >= 0.2
        event_dt = final.fda_dt - dt.timedelta(days=rng.randint(5, 400))
        case = Case(
            caseid, age, rng.choice("FM"), rng.choice(COUNTRIES),
            event_dt if known else None, [],
        )  # fmt: skip
        # Two different patients never share every identifying field.
        if case.patient is None or case.patient not in patients:
            break
    if case.patient is not None:
        patients.add(case.patient)
    case.versions = _with_earlier(rng, final, drug, event)
    return case


def _duplicate(
    rng: random.Random,
    caseid: int,
    case: Case,
    drug: str,
    event: str,
    with_drug: list[str],
) -> Case:
    """The same patient reported again, by another reporter, with details
    that differ: the event added or dropped, another product for the drug."""
    final = case.versions[-1]
    copy = Version(
        _random_date(rng, dt.date(2024, 6, 1), dt.date(2025, 9, 30)),
        [
            (rng.choice(with_drug) if drug in PRODUCTS[p] else p, role)
            for p, role in final.drugs
        ],
        [r for r in final.reactions if r != event],
    )
    if event not in final.reactions or rng.random() < 0.2:
        copy.reactions.append(event)
    if not copy.reactions:
        copy.reactions = ["Nausea"]
    while copy.fda_dt == final.fda_dt:
        copy.fda_dt += dt.timedelta(days=1)
    dup = Case(caseid, case.age, case.sex, case.country, case.event_dt, [])
    dup.versions = _with_earlier(rng, copy, drug, event)
    return dup


def _with_earlier(
    rng: random.Random, final: Version, drug: str, event: str
) -> list[Version]:
    """The final version and the earlier ones a follow-up corrected: the event
    added or removed, or the drug's role changed."""
    r = rng.random()
    versions = [final]
    for _ in range(0 if r < 0.75 else 1 if r < 0.95 else 2):
        later = versions[0]
        v = Version(
            later.fda_dt - dt.timedelta(days=rng.randint(10, 120)),
            list(later.drugs),
            list(later.reactions),
        )
        if event in v.reactions:
            v.reactions.remove(event)
        elif rng.random() < 0.5:
            v.reactions.append(event)
        if rng.random() < 0.5:
            v.drugs = [
                (p, "C" if role == "PS" and drug in PRODUCTS[p] else role)
                for p, role in v.drugs
            ]
        if not v.reactions:
            v.reactions = ["Nausea"]
        versions.insert(0, v)
    return versions


def _random_date(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=rng.randint(0, (end - start).days))


def _yyyymmdd(day: dt.date | None) -> str:
    return "" if day is None else day.strftime("%Y%m%d")


def _messy(rng: random.Random, name: str) -> str:
    name = rng.choice((name, name.lower(), name.title()))
    return rng.choice(("", " ")) + name + rng.choice(("", " ", "  "))


def _messy_term(rng: random.Random, term: str) -> str:
    return rng.choice((term, term, term.upper(), term.lower()))


def _csv(header: tuple[str, ...], rows: list[tuple]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()
