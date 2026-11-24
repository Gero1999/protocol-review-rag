import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag_review.workflow import DEFAULT_QUESTION, ReviewPlan, ask, make_langchain_planner

STUDY = Path(__file__).resolve().parents[1] / "demo" / "study"


class WorkflowTests(unittest.TestCase):
    def test_protocol_data_overview_runs_all_supported_checks_locally(self):
        planner = Mock(side_effect=AssertionError("A standard review does not need a model."))
        for question in (
            DEFAULT_QUESTION,
            "Summarize differences between data and protocol.",
            "Compare the data against the protocol.",
        ):
            with self.subTest(question=question):
                result = ask(STUDY, question, planner=planner)
                self.assertEqual(result["status"], "answered")
                self.assertEqual(
                    [check["check_id"] for check in result["checks"]],
                    ["visit3_timing", "visit3_bp", "visit3_chemistry"],
                )
                self.assertIn("Visit 3 timing, blood pressure, and chemistry", result["answer"].splitlines()[0])
        planner.assert_not_called()

    def test_general_review_runs_three_cited_checks(self):
        result = ask(STUDY, "Which Visit 3 records need review?")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(
            [check["check_id"] for check in result["checks"]],
            ["visit3_timing", "visit3_bp", "visit3_chemistry"],
        )
        available = {source["id"]: source for source in result["sources"]}
        for check in result["checks"]:
            self.assertEqual(check["denominator"], 30)
            for version in ("1", "2"):
                source = available[check["source_ids"][version]]
                self.assertEqual(source["version"], version)
                self.assertEqual(source["document"], f"protocol-v{version}.md")
            self.assertEqual(available[check["source_ids"]["unknown"]]["section"], "Version applicability")

    def test_amendment_answer_quotes_both_versions_without_running_sql(self):
        with patch("rag_review.workflow.run_check") as check:
            result = ask(STUDY, "What changed in v2?")
        check.assert_not_called()
        self.assertEqual(result["status"], "answered")
        self.assertIn("day 12 through day 16", result["answer"])
        self.assertIn("day 13 through day 17", result["answer"])
        self.assertIn("amendment-01:visit-3-timing-amendment", [source["id"] for source in result["sources"]])

    def test_targeted_check_with_a_structured_langchain_planner(self):
        model = Mock()
        structured = model.with_structured_output.return_value
        structured.invoke.return_value = ReviewPlan(mode="records", checks=["visit3_chemistry"])

        result = ask(STUDY, "Which Visit 3 lab results are missing?", make_langchain_planner(model))

        model.with_structured_output.assert_called_once_with(ReviewPlan)
        planner_input = structured.invoke.call_args.args[0]
        self.assertIn("Visit 3 chemistry", planner_input[1][1])
        self.assertNotIn("AB-008", planner_input[1][1])
        self.assertEqual([check["check_id"] for check in result["checks"]], ["visit3_chemistry"])
        self.assertIn("1 without a usable result", result["answer"])

    def test_invalid_planner_output_cannot_invoke_checks(self):
        planner = Mock(return_value={
            "mode": "records", "checks": ["visit3_timing"], "sql": "SELECT * FROM subjects",
        })
        with patch("rag_review.workflow.run_check") as check:
            result = ask(STUDY, "Which Visit 3 visits were late?", planner)
        check.assert_not_called()
        self.assertEqual(result["status"], "planner_error")

    def test_requests_outside_supported_checks_or_scope_are_not_run(self):
        with patch("rag_review.workflow.run_check") as check:
            for question in (
                "Does the data show that the intervention is effective?",
                "Which Visit 4 records need review?",
                "Summarize differences between data and protocol for Visit 4.",
                "What are the inclusion criteria for Visit 3?",
                "Which Visit 3 records need review under protocol-2?",
                "Which Site A Visit 3 records need review?",
                "Which Visit 3 records are missing labs for participant AB-005?",
            ):
                with self.subTest(question=question):
                    self.assertEqual(ask(STUDY, question)["status"], "unsupported")
        check.assert_not_called()

    def test_a_missing_reviewed_citation_prevents_sql_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory) / "study"
            shutil.copytree(STUDY, study)
            second_protocol = study / "docs" / "protocol-v2.md"
            protocol = second_protocol.read_text(encoding="utf-8")
            second_protocol.write_text(
                protocol.replace("## Visit 3 chemistry", "## Chemistry notes"),
                encoding="utf-8",
            )
            with patch("rag_review.workflow.run_check") as check:
                result = ask(study, "Which Visit 3 lab results are missing?")
        check.assert_not_called()
        self.assertEqual(result["status"], "insufficient_sources")
