# Jev document classification trial

The trial is an offline-first tool, separate from discovery and publication.
It uses TypeSafe's [Choice API](https://docs.typesafe.ai/primitives/choice)
with the pinned `jev-1.13.0` text model. It cannot approve schedules, change
production routing, or publish closures. There is no scheduled paid job.

## Prepare independent evidence

Capture historical official documents and extract their text. Review the
original documents independently of Jev, recording the reviewer, date,
source URL, and rationale in `review`. Do not use Jev output or an extractor's
own output as its reference labels. The categories are `session_grid`,
`closure_notice`, `other`, and `uncertain`. Facility opening hours are `other`;
a timetable with incidental holiday notes is still a `session_grid`.

Keep each pool/season entirely in development or holdout. Reserve later
seasons before tuning the question or choosing a confidence threshold.
Include closure notices, partial grids, facility hours, flyers, and ambiguous
sources; a corpus containing only timetables cannot establish closure safety.
Text extraction can lose visual evidence, so keep the original documents
alongside the text for review. Image classification is outside this trial.

Write a TOML manifest beside the text captures, for example:

```toml
[[documents]]
id = "pool-season-document"
text_path = "document.txt"
text_sha256 = "REPLACE_WITH_SHA256_OF_UTF8_TEXT"
expected = "closure_notice"
split = "development"
pool_season = "pool-2026-fall"
review = "Reviewer; date; official URL; evidence and classification rationale"
```

IDs and content hashes must be unique. Changed text and pool/season leakage
fail validation. The manifest's review field is provenance, not automatic
proof that a human reviewed it. Synthetic unit-test cases exercise the tool;
they are not a historical benchmark or evidence of model quality.

## Run inside the project sandbox

Use the [sandbox workflow](sandboxes.md). Follow [Task credentials](secrets.md) to store the TypeSafe key in the host
Keychain and grant the sandbox its proxy placeholder, then explicitly request
paid calls:

```sh
devenv shell -- uv --project schedule-tools run python -m schedules.jev_trial \
  tmp/jev/cases.toml --responses tmp/jev/responses.json \
  --output tmp/jev/report.json --threshold 0.8 --request
```

`TYPESAFE_API_KEY` is required only for `--request`. Never put it in the
manifest or commit it. The threshold above is illustrative, not a calibrated
recommendation. Requests send the captured text, not the reference labels.
The tool makes one request per document with a 60-second timeout and no
retries. Completed responses, including usage, are saved after every call;
an interrupted run preserves those responses and exits unsuccessfully.
It refuses to overwrite a response capture in request mode.

Omit `--request` to replay the saved responses without credentials or network
access. Choose a new output path for every report. A replay requires exactly
one response for each manifest entry and validates the pinned model, question
and source fingerprint, confidence, and probability distribution. After a
partial run, use a matching subset manifest for replay; capture remaining
cases into a separate new response file to avoid paying for completed calls.

Report development and holdout results separately. The output records
classification errors, accepted errors, abstentions, coverage, missed
closures among accepted decisions, and closure abstentions. `reviews_avoided`
remains null: correct classification alone does not establish that an operator
review was actually avoided. Model confidence is not measured correctness.

A successful replay validates the evaluation machinery only. Before any
production proposal, run the historical corpus, select a threshold using
only development data, report untouched holdout results, compare with current
discovery decisions, and then observe disagreements alongside production.
Keep all existing extraction and publication gates in place.
