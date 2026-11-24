# Synthetic study packet

The protocol, amendment, participant IDs, dates, and measurements were
created for this demo. The CSVs cover a small subset of the fields a
submission may contain. The reviewed mappings are specific to this study.

- `subjects.csv` defines the expected Visit 3 cohort, anchor date, and
  applicable version for each participant.
- `sv.csv`, `vs.csv`, and `lb.csv` carry observed visit, blood pressure,
  and chemistry records.
- `rules.json` holds reviewed windows and test code mappings for both versions.
- `expected_findings.json` is a test fixture. Subjects omitted from a check's
  list of flags are expected to pass that check.

Regenerate the CSVs with `python scripts/generate_study.py` from the repo
root. To preserve the supplied study, use `--output` with another directory.
