"""The adverse-event data, its PRR, and the mistakes that must get it wrong."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from environment.tasks.adverse_event_signal import data
from environment.tasks.adverse_event_signal.reference_solution import solve

SEEDS = (0, 1, 2)
REFERENCE = Path(data.__file__).parent / "reference_solution.py"

# Each is a plausible slip by a solution that reads the files carefully but not
# carefully enough; each must change the PRR on its own.
MISTAKES = (
    "all_versions",
    "keep_deleted",
    "no_dedup",
    "dedup_blank_patients",  # Treats cases missing age or event_dt as one patient.
    "dedup_keeps_oldest",
    "single_ingredient_only",  # Matches prod_ai exactly, so misses combinations.
    "names_without_dictionary",
    "any_role",
    "no_term_mapping",
    "keep_empty_cases",
)


@pytest.fixture(params=SEEDS, scope="module")
def run(request, tmp_path_factory):
    seed = request.param
    ds = data.generate(seed)
    root = tmp_path_factory.mktemp(f"seed{seed}")
    for name, content in data.to_csv(ds, seed).items():
        (root / name).write_bytes(content)
    return root, ds


def test_the_reference_solution_finds_the_answer(run):
    root, ds = run
    assert solve(str(root), ds.drug, ds.event) == data.expected_answer(ds)


def test_the_reference_solution_runs_as_a_script(run):
    root, ds = run
    out = subprocess.run(
        [sys.executable, "-I", str(REFERENCE), str(root), ds.drug, ds.event],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == data.expected_answer(ds)


def test_the_answer_shows_a_signal(run):
    _, ds = run
    assert float(data.expected_answer(ds)) > 2


def test_the_answer_is_not_near_a_rounding_edge(run):
    _, ds = run
    hundredths = data.prr(ds) * 100
    assert abs(hundredths - int(hundredths) - 0.5) > 0.01


def test_generation_is_deterministic():
    assert data.to_csv(data.generate(7), 7) == data.to_csv(data.generate(7), 7)
    assert data.to_csv(data.generate(7), 7) != data.to_csv(data.generate(8), 8)


def test_two_patients_never_look_like_one():
    for seed in SEEDS:
        ds = data.generate(seed)
        by_patient: dict[tuple, int] = {}
        for case in ds.cases:
            if case.patient is not None:
                by_patient[case.patient] = by_patient.get(case.patient, 0) + 1
        assert max(by_patient.values()) == 2


@pytest.mark.parametrize("mistake", MISTAKES)
def test_each_mistake_gets_a_different_answer(run, mistake):
    root, ds = run
    assert _prr(root, ds, mistake) != data.expected_answer(ds)


def test_the_mistake_counter_without_a_mistake_is_right(run):
    root, ds = run
    assert _prr(root, ds, None) == data.expected_answer(ds)


def _prr(root: Path, ds: data.Dataset, mistake: str | None) -> str:
    """The rules written another way, with one mistake switched on."""

    def rows(name):
        with open(root / name, newline="") as f:
            return list(csv.DictReader(f))

    prod_ai = {
        r["drugname"].strip().upper(): r["prod_ai"] for r in rows("drug_dictionary.csv")
    }
    pt = {r["llt"].lower(): r["pt"].lower() for r in rows("meddra.csv")}
    deleted = (
        set()
        if mistake == "keep_deleted"
        else {r["caseid"] for r in rows("deleted_cases.csv")}
    )

    reports = [r for r in rows("reports.csv") if r["caseid"] not in deleted]

    def patient(r: dict) -> tuple | None:
        if not (r["age"] and r["event_dt"]) and mistake != "dedup_blank_patients":
            return None
        return (r["age"], r["sex"], r["occr_country"], r["event_dt"])

    def newer(r: dict, other: dict) -> bool:
        return (r["fda_dt"] < other["fda_dt"]) == (mistake == "dedup_keeps_oldest")

    latest: dict[str, dict] = {}
    for r in reports:
        if mistake == "all_versions":
            latest[r["primaryid"]] = r
        elif r["caseid"] not in latest or int(r["caseversion"]) > int(
            latest[r["caseid"]]["caseversion"]
        ):
            latest[r["caseid"]] = r
    chosen: dict[tuple, dict] = {}
    for r in latest.values():
        key = patient(r)
        if mistake in ("no_dedup", "all_versions") or key is None:
            chosen[(r["primaryid"],)] = r
        elif key not in chosen or newer(r, chosen[key]):
            chosen[key] = r
    keep = {r["primaryid"] for r in chosen.values()}

    def is_drug(name: str) -> bool:
        if mistake == "names_without_dictionary":
            return ds.drug in name.lower()
        ingredients = prod_ai.get(name.strip().upper(), "")
        if mistake == "single_ingredient_only":
            return ingredients == ds.drug.upper()
        return ds.drug.upper() in ingredients.split("\\")

    exposed = {
        r["primaryid"]
        for r in rows("drugs.csv")
        if r["primaryid"] in keep
        and (mistake == "any_role" or r["role_cod"] == "PS")
        and is_drug(r["drugname"])
    }
    reacted, evented = set(), set()
    for r in rows("reactions.csv"):
        if r["primaryid"] in keep:
            reacted.add(r["primaryid"])
            term = r["pt"].lower()
            if (term if mistake == "no_term_mapping" else pt[term]) == ds.event.lower():
                evented.add(r["primaryid"])
    universe = keep if mistake == "keep_empty_cases" else reacted
    exposed &= universe
    a = len(exposed & evented)
    b = len(exposed - evented)
    c = len(evented - exposed)
    d = len(universe - exposed - evented)
    return f"{(a / (a + b)) / (c / (c + d)):.2f}"
