# Protocol to SDTM Review

Ask how a fictional clinical study's records align with its protocol. The
demo finds the governing requirements, runs reproducible checks, and shows
the source rows behind each finding.

## Run the demo

Use Python 3.12 from the repository root.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local URL Streamlit prints and submit the prefilled question,
**Summarize discrepancies between the data and the protocol**. It runs all
three supported checks for Visit 3 timing, blood pressure, and chemistry.
Select a check and a flagged participant to inspect the evidence. For a
follow-up, try **Which Visit 3 records need review?** or **What changed for
Visit 3 in protocol version 2?**

The default mode runs locally and does not require a model or API key.
Setting `OPENAI_API_KEY` on the server enables optional OpenAI question
routing for questions outside the standard comparison. That mode sends the
question and retrieved fictional protocol excerpts to the model. The supplied
CSV rows and the DuckDB checks stay local. `OPENAI_MODEL` can override the
default model.

## How it works

- LangChain retrieves complete protocol sections with document and version
  labels.
- A local router or a structured model response selects from three
  predefined Visit 3 checks. The [reviewed study rules](demo/study/rules.json)
  supply the window and test codes.
- DuckDB checks the mapped cohort and returns counts and flagged records.
  Results distinguish discrepancies, missing records, and records that
  cannot be assessed.

The [Aster Brook study](demo/study/README.md) uses original documents and
synthetic, SDTM-style records. The [design](docs/design.md) explains the
scope and assumptions of the review.

## Verify the findings

```bash
python -m unittest discover -s tests -v
```

The supplied study has 30 participants expected at Visit 3. The timing
check finds two visits outside the window, one missing visit record, and
three records that cannot be assessed. The [expected findings](demo/study/expected_findings.json)
list the affected participants for all three checks. The test suite compares
them with the results from the same question and workflow used in the app.
