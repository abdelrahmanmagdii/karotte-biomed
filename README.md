# karotte-biomed

Two RL environments for biomedical data work, built on [Karotte](https://github.com/preferencemodel/karotte). All data is synthetic and generated fresh for each run from a seed. No real patient or report data is used.

## Tasks

**cohort-query.** Count a type 2 diabetes cohort in a SQLite database laid out like the PCORnet Common Data Model. The data includes patients registered under two IDs, type 1 diabetes coded in ICD-9, a 365-day washout window, HbA1c in two units, and results above the analyzer's range stored only as text.

**adverse-event-signal.** Compute a proportional reporting ratio (PRR) from CSV files laid out like FDA's FAERS. The data includes several versions of each case, deleted cases, the same patient reported under two case IDs, combination products such as JANUMET, and reaction terms that need mapping to preferred terms.

The answer is computed from the clean data before it is made messy, and stored where the model can't read it. The model has to write a single number to a file. Guessing or listing several answers scores 0.

Each task folder has a README with the details, and the tests check that every common mistake changes the answer.

## Results

One run per model, without hints.

| Model | cohort-query | adverse-event-signal |
|---|---|---|
| GLM 5.3 | 0 | 1 |
| Kimi K3.1 Pro | 1 | 1 |
| Claude Sonnet 5.5 | 1 | 1 |

In the first version, every model solved both tasks, so I added the harder cases above. GLM 5.3 then answered 81 instead of 103 on the cohort task: it saw that some results were stored as `>14.0` but still dropped them. The adverse-event task is still solved by all three.

## Running it

```bash
uv sync --extra dev
uv run --extra test pytest
uv run karotte build
uv run karotte run --config run_config.json --runtime docker
```

`run_config.json` names the task (`cohort-query` or `adverse-event-signal`) and the model. Set `use_hints` to `false` to leave the data hints out of the instructions, and `extra_config.seed` to fix the data.
