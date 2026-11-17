## Background

Cohort counts are the first step of most observational studies on electronic health records: find patients with a condition, anchor each at an index date, and apply exclusion, age, lab and enrollment criteria relative to it. Networks such as PCORnet share a common data model so the same query runs at every site.

## Motivation

The criteria are easy to state and easy to get subtly wrong. The task checks that the student inspects the data before trusting it:

- type 1 diabetes coded in ICD-9 (250.x1 and 250.x3) as well as ICD-10, next to ICD-9 type 2 codes that must not exclude anyone;
- HbA1c in % and mmol/mol, and results above the analyzer's range stored with no `RESULT_NUM`, only `RESULT_MODIFIER` `GT` and `RAW_RESULT` `>14.0`, next to cancelled results that are also empty;
- people registered under two PATIDs, listed in `PATID_MERGE`, with their diagnoses, labs and visits split between them;
- a washout window of visits 1 to 365 days before the index date, where the index visit itself doesn't count;
- birthdays on and one day after the index date, labs near a later diagnosis but outside the first one's window, glucose results, codes with and without the dot, and duplicated rows.

In a first version with only the last group of traps, every model we tried (GLM 5.3, Kimi K3.1 Pro, Claude Sonnet 5.5) got the count right without hints. The traps above were added so that routine data inspection is no longer enough.

## Data

`pre_hook` generates 2,000 people (`extra_config["patients"]`) from a fresh seed every run (`extra_config["seed"]` pins it) and writes `/workdir/shared/cohort/cohort.db`, read-only, with the tables `DEMOGRAPHIC`, `PATID_MERGE`, `ENCOUNTER`, `DIAGNOSIS` and `LAB_RESULT_CM`. The count is computed from the clean patient model before the data is made messy, and stored in the `ProtectedStore`. Nothing in the image holds the answer.

`reference_solution.py` solves the task from the database alone. The tests check that it matches the count for several seeds, and that each of ten plausible mistakes, such as dropping rows with no `RESULT_NUM` or counting PATIDs instead of people, gives a different count.

## Scoring

1 if `/workdir/data/answer.txt` holds exactly one non-negative integer equal to the count, else 0. A list of guesses or any extra text scores 0. Scoring metadata records the expected and submitted answers and the seed.

## Hints

With `use_hints`, the instructions point out the two code formats, the mmol/mol results with the conversion formula, the results above the analyzer's range, the merged PATIDs and the duplicated rows.
