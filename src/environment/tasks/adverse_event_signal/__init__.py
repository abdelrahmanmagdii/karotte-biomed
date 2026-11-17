import re
from pathlib import Path
from textwrap import dedent
from typing import final

from karotte import ProtectedStore, Step, Task
from pydantic import BaseModel

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
from environment.tasks.adverse_event_signal import data

DATA_DIR = SHARED_DATA_DIR / "faers"
ANSWER_PATH = STUDENT_DATA_DIR / "answer.txt"


class Question(BaseModel):
    """Which pair this run asks about. Not secret, but only known after
    `pre_hook`, so the instructions read it from here."""

    drug: str
    event: str


@final
class AdverseEventSignal(Task):
    id = "adverse-event-signal"

    @property
    def system_prompt(self) -> str:
        return get_system_prompt(self.config.model, self.config.extra_config)

    def pre_hook(self):
        # The data, the drug-event pair and the answer are made fresh for every run.
        seed = run_seed(self.config)
        n = (self.config.extra_config or {}).get("cases", data.DEFAULT_CASES)
        ds = data.generate(seed, n)
        provision_read_only(DATA_DIR, data.to_csv(ds, seed))
        ProtectedStore().write(_question_name(), Question(drug=ds.drug, event=ds.event))
        store_answer(self.id, Answer(expected=data.expected_answer(ds), seed=seed))
        return {"cases": n, "drug": ds.drug, "event": ds.event}

    @property
    def steps(self):
        return [ComputePrrStep(config=self.config)]

    @property
    def tools(self):
        return ["bash", "view_lines_in_file", "replace_in_file"]


class ComputePrrStep(Step):
    saved_submissions: tuple[Path, ...] = ()

    @property
    def submission_paths(self) -> tuple[Path, ...]:
        return (ANSWER_PATH,)

    @property
    def instructions(self) -> str:
        q = ProtectedStore().read(_question_name(), Question)
        prompt = dedent(f"""
            {DATA_DIR} holds spontaneous adverse-event reports in the layout of
            FDA's FAERS quarterly files: reports.csv, drugs.csv, reactions.csv,
            deleted_cases.csv, drug_dictionary.csv, which gives the active
            ingredients (prod_ai) of every drug name used in drugs.csv, and
            meddra.csv, which maps MedDRA lowest level terms (llt) to preferred
            terms (pt). Python 3 with the standard library is available; there
            is no network access.

            Compute the proportional reporting ratio (PRR) of {q.drug} for the
            preferred term "{q.event}":

                PRR = (a / (a + b)) / (c / (c + d))

            where a is the number of cases that report the drug and the reaction,
            b the drug without the reaction, c the reaction without the drug, and
            d neither. Count cases, not reports, with these rules, in this order:

            1. A case can have several versions (caseversion). Use only the latest
               version of each case and ignore the earlier ones.
            2. Leave out every case listed in deleted_cases.csv.
            3. Two cases with the same age, sex, occr_country and event_dt are
               reports of the same patient: keep only the one whose latest
               version has the most recent fda_dt. Cases missing age or event_dt
               are never treated as duplicates.
            4. Leave out cases whose latest version lists no reaction.

            A case reports {q.drug} if a drug in it with role_cod PS (primary
            suspect) has {q.drug} among its active ingredients. Look drug names
            up in drug_dictionary.csv ignoring letter case and leading or
            trailing whitespace. The reaction terms in reactions.csv are lowest
            level terms: map each to its preferred term with meddra.csv,
            ignoring letter case, and compare preferred terms.

            Write only the PRR rounded to two decimal places, for example 3.47,
            to {ANSWER_PATH}.
            """)
        if self.config.use_hints:
            prompt += dedent("""
                Hints: the rows are not sorted, so find each case's latest version
                by comparing caseversion. Drug names include brand, salt and
                combination product names; prod_ai separates ingredients with a
                backslash. The drug sometimes appears with role SS or C, which
                doesn't count. Many cases have no age or event_dt.
                """)
        return prompt

    @property
    def judge(self):
        assert self.saved_submissions, "pre_scoring_hook has not run"
        return AnswerJudge(
            self.saved_submissions[0],
            re.compile(r"[0-9]+\.[0-9]{2}"),
            read_answer(AdverseEventSignal.id),
        )

    def pre_scoring_hook(self):
        self.saved_submissions = collect_submission(self.config, self.submission_paths)


def _question_name() -> str:
    return f"{AdverseEventSignal.id}-question"
