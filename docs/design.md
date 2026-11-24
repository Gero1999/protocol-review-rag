# Protocol to SDTM review

A clinical study reviewer asks which Visit 3 records need review. The app
shows the governing protocol passage, the check it ran, and the data behind
each finding. The demo uses an original protocol, an amendment, and
synthetic CSVs modeled on a subset of the SDTM SV, VS, and LB domains.

## First study

The fictional study expects one Visit 3 per subject. Count calendar days
from randomization, which is day zero. Version 1 allows days 12–16 and
version 2 allows days 13–17, inclusive. Both versions expect systolic and
diastolic blood pressure, glucose, and creatinine at Visit 3.

A study mapping identifies the participants expected at Visit 3, their
randomization dates, and their applicable protocol versions. For the demo,
the mapping declares applicability per participant. A missing assignment
makes the version uncertain. The applicability decision is never inferred
from a visit date or the presence of the latest protocol in the corpus.

## Review workflow

1. Find relevant protocol sections and keep the document version and
   section attached to each passage. Keep schedule table rows together
   with their headings.
2. Select a supported check. Reviewed rules supply the window and test
   codes. Model output can select check IDs and citations.
3. Run fixed DuckDB queries against the supplied tables. Count statuses
   over the participants expected to have Visit 3. Separate a late or
   early visit, no matching visit, missing results, and cases where the
   records do not support an assessment.
4. Present the counts, source passages, and flagged data. A missing
   matching result is a reason to review the supplied data. It does not
   establish that an assessment was missed or that a deviation occurred.

The public demo uses only the bundled synthetic study. The CSVs are designed
for this workflow and do not represent a submission-ready SDTM package.
The first version checks record alignment. It does not diagnose patients,
interpret laboratory values, or determine regulatory compliance.

## Development references

- [CDISC SDTM](https://www.cdisc.org/standards/foundational/sdtm)
- [LangChain Python documentation](https://docs.langchain.com/oss/python/langchain/overview)
- [DuckDB CSV documentation](https://duckdb.org/docs/stable/data/csv/overview)
