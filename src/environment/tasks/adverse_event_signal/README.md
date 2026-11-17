## Background

Pharmacovigilance teams screen spontaneous adverse-event reports, such as FDA's FAERS, for drug-event pairs reported more often than expected. The proportional reporting ratio (PRR) compares how often an event is reported with a drug against how often it is reported with all other drugs.

## Motivation

The formula is simple; the data preparation is where it goes wrong. The task checks that the student:

- keeps only the latest version of each case, then drops the cases FDA deleted;
- removes duplicate reports of the same patient filed under different case ids, keeping the most recent one, without merging the many cases that are missing age or event date;
- finds the drug in combination products such as JANUMET (sitagliptin and metformin), not only in its brand and salt names;
- counts the drug only as primary suspect;
- maps reaction terms recorded as MedDRA lowest level terms, such as "Acidosis lactic" or the US spelling "Hemorrhage", to their preferred terms;
- leaves out cases without reactions.

Each of these changes the answer at two decimals. In a first version with only versions, brand names, roles and empty cases, every model we tried (GLM 5.3, Kimi K3.1 Pro, Claude Sonnet 5.5) got the PRR right without hints.

## Data

`pre_hook` generates 3,000 cases plus duplicates (`extra_config["cases"]`) from a fresh seed every run (`extra_config["seed"]` pins it), picks metformin, atorvastatin or lisinopril with its known signal, and writes `reports.csv`, `drugs.csv`, `reactions.csv`, `deleted_cases.csv`, `drug_dictionary.csv` and `meddra.csv` to `/workdir/shared/faers/`, read-only. The drug names are real; the term hierarchy is a small synthetic stand-in for MedDRA. The PRR is computed exactly, with fractions, from the clean case model, and the data is regenerated when the PRR would land within 0.0001 of a rounding edge. The answer is stored in the `ProtectedStore`.

`reference_solution.py` solves the task from the CSVs alone. The tests check that it matches for several seeds, and that each of ten plausible mistakes, such as matching `prod_ai` exactly or grouping cases with blank ages as one patient, gives a different answer.

## Scoring

1 if `/workdir/data/answer.txt` holds exactly one number with two decimals equal to the PRR rounded to two decimals, else 0. A list of guesses or any extra text scores 0.

## Hints

With `use_hints`, the instructions point out the unsorted versions, the brand, salt and combination product names, the SS and C roles, and the cases with no age or event date.
