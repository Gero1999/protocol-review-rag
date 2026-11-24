import json
import os
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from rag_review.workflow import DEFAULT_QUESTION, ask
from scripts.generate_study import HEADERS, generate


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "demo" / "study"


class DemoTests(unittest.TestCase):
    def test_generated_tables_match_the_committed_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            generate(output)
            for table in HEADERS:
                with self.subTest(table=table):
                    filename = f"{table}.csv"
                    self.assertEqual((output / filename).read_bytes(), (STUDY / filename).read_bytes())

    def test_review_matches_expected_records_and_links_both_versions(self):
        expected = json.loads((STUDY / "expected_findings.json").read_text(encoding="utf-8"))
        result = ask(STUDY, DEFAULT_QUESTION)
        self.assertEqual(result["status"], "answered")
        self.assertEqual({check["check_id"] for check in result["checks"]}, set(expected["checks"]))
        sources = {source["id"]: source for source in result["sources"]}
        for check in result["checks"]:
            with self.subTest(check=check["check_id"]):
                self.assertEqual(check["denominator"], expected["denominator"])
                flags = defaultdict(list)
                for finding in check["findings"]:
                    if finding["status"] != "pass":
                        flags[finding["status"]].append(finding["USUBJID"])
                self.assertEqual(dict(flags), expected["checks"][check["check_id"]])
                self.assertEqual(set(check["source_ids"]), {"1", "2", "unknown"})
                for version in ("1", "2"):
                    identifier = check["source_ids"][version]
                    self.assertEqual(sources[identifier]["version"], version)
                    self.assertEqual(sources[identifier]["document"], f"protocol-v{version}.md")
                self.assertEqual(sources[check["source_ids"]["unknown"]]["section"], "Version applicability")

    def test_amendment_answer_cites_the_two_different_windows(self):
        result = ask(STUDY, "What changed for Visit 3 in protocol version 2?")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["checks"], [])
        self.assertIn("day 12 through day 16", result["answer"])
        self.assertIn("day 13 through day 17", result["answer"])
        self.assertIn("amendment-01.md", {source["document"] for source in result["sources"]})

    def test_demo_opens_and_exposes_the_rows_for_a_flag(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            app = AppTest.from_file(str(ROOT / "app.py"))
            app.run()
            self.assertEqual(app.text_input(key="question").value, DEFAULT_QUESTION)
            self.assertIn("Which Visit 3 records need review?", [button.label for button in app.button])
            next(button for button in app.button if button.label == "Review study").click()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual([tab.label for tab in app.tabs], ["Visit timing", "Blood pressure", "Chemistry"])
            app.selectbox(key="review-visit3_timing").select("SUBJ-002").run()
            self.assertFalse(app.exception)
            self.assertIn("SUBJ-002", app.json[0].value)
            self.assertIn("Visit 3 timing · protocol-v2.md", [item.label for item in app.expander])
            mapping, visit = (
                table.value for table in app.dataframe if "USUBJID" in table.value.columns
            )
            self.assertEqual(mapping.at[0, "PROTOCOL_VERSION"], "2")
            self.assertEqual(visit.at[0, "SVSTDTC"], "2025-01-24")
            app.selectbox(key="review-visit3_timing").select("SUBJ-006").run()
            self.assertIn("Version applicability · amendment-01.md", [item.label for item in app.expander])


if __name__ == "__main__":
    unittest.main()
