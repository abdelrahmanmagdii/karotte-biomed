import re
from pathlib import Path
from textwrap import dedent
from typing import final

from karotte import Step, Task

from environment.answers import (
    Answer,
    AnswerJudge,
    provision_read_only,
    read_answer,
    run_seed,
    store_answer,
)
from environment.paths import SHARED_DATA_DIR, STUDENT_DATA_DIR
from environment.submissions import collect_submission
from environment.system_prompts import get_system_prompt
from environment.tasks.cohort_query import data

DATA_DIR = SHARED_DATA_DIR / "cohort"
DB_PATH = DATA_DIR / "cohort.db"
ANSWER_PATH = STUDENT_DATA_DIR / "answer.txt"


@final
class CohortQuery(Task):
    id = "cohort-query"

    @property
    def system_prompt(self) -> str:
        return get_system_prompt(self.config.model, self.config.extra_config)

    def pre_hook(self):
        # The data and its answer are made fresh for every run.
        seed = run_seed(self.config)
        n = (self.config.extra_config or {}).get("patients", data.DEFAULT_PATIENTS)
        patients = data.generate(seed, n)
        provision_read_only(DATA_DIR, {DB_PATH.name: data.to_sqlite(patients, seed)})
        expected = sum(data.in_cohort(p) for p in patients)
        store_answer(self.id, Answer(expected=str(expected), seed=seed))
        return {"patients": n}

    @property
    def steps(self):
        return [CountCohortStep(config=self.config)]

    @property
    def tools(self):
        return ["bash", "view_lines_in_file", "replace_in_file"]


class CountCohortStep(Step):
    saved_submissions: tuple[Path, ...] = ()

    @property
    def submission_paths(self) -> tuple[Path, ...]:
        return (ANSWER_PATH,)

    @property
    def instructions(self) -> str:
        prompt = dedent(f"""
            {DB_PATH} is a read-only SQLite database of electronic health records
            in a subset of the PCORnet Common Data Model. Python 3 with the
            standard library is available; there is no network access.

            Count the people who meet all of these criteria, counting each
            person once:

            1. They have at least one ICD-10-CM diagnosis (DX_TYPE '10') in
               category E11, type 2 diabetes mellitus. Their earliest such
               diagnosis date (ADMIT_DATE) is their index date.
            2. They have never had a type 1 diabetes diagnosis: ICD-10-CM
               category E10, or ICD-9-CM (DX_TYPE '09') 250.x1 or 250.x3, where
               a fifth digit of 1 or 3 means type 1.
            3. They were at least 65 years old, in completed years, on their
               index date.
            4. They had at least one encounter in the 365 days before their
               index date, from 365 days before it up to the day before it, so
               the diagnosis is a new one rather than the first record of a
               patient new to the system.
            5. They have at least one HbA1c result (LOINC 4548-4 or 17856-6)
               above 9.0% (NGSP) dated from the index date up to and including
               90 days after it.

            Write only the count as an integer, for example 137, to {ANSWER_PATH}.
            """)
        if self.config.use_hints:
            prompt += dedent("""
                Hints: diagnosis codes are stored both with and without the dot
                (E11.9 and E119). Some HbA1c results are reported in mmol/mol
                (IFCC) rather than %; NGSP % = 0.09148 * mmol/mol + 2.152.
                Results above the analyzer's range have no RESULT_NUM: their
                RESULT_MODIFIER is GT and RAW_RESULT holds the bound. Some
                people were registered under two PATIDs; PATID_MERGE maps each
                retired PATID to the one that replaced it, and their records
                can be under either. Some rows are duplicated.
                """)
        return prompt

    @property
    def judge(self):
        assert self.saved_submissions, "pre_scoring_hook has not run"
        return AnswerJudge(
            self.saved_submissions[0],
            re.compile(r"[0-9]+"),
            read_answer(CohortQuery.id),
            same=lambda a, b: int(a) == int(b),
        )

    def pre_scoring_hook(self):
        self.saved_submissions = collect_submission(self.config, self.submission_paths)
