import tempfile
import unittest
from pathlib import Path

from rag_review.retrieval import load_passages, retrieve


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.study_dir = Path(directory.name)
        self.docs = self.study_dir / "docs"
        self.docs.mkdir()
        for version, window in ("1", "12 to 16"), ("2", "13 to 17"):
            (self.docs / f"protocol-v{version}.md").write_text(
                f"# Protocol {version}\n\n"
                f"## Visit 3 timing\n\n"
                f"Visit 3 occurs {window} days after randomization.\n\n"
                "## Visit 3 chemistry\n\n"
                "| Test | Units |\n"
                "| --- | --- |\n"
                "| Glucose | mmol/L |\n"
                "| Creatinine | umol/L |\n\n"
                "## Visit 3 blood pressure\n\n"
                "Record systolic and diastolic blood pressure.\n\n"
                "## Applicability and scope\n\n"
                "Use the protocol assigned at randomization.\n",
                encoding="utf-8",
            )
        (self.docs / "amendment-01.md").write_text(
            "# Amendment 01\n\n"
            "## Visit 3 timing amendment\n\n"
            "This change moves the window for Visit 3 from days 12–16 to 13–17.\n",
            encoding="utf-8",
        )

    def test_retrieval_keeps_the_schedule_table_intact(self):
        passages = retrieve(self.study_dir, "Which lab results are expected at Visit 3?", 2)
        self.assertEqual([passage["id"] for passage in passages], [
            "protocol-v1:visit-3-chemistry", "protocol-v2:visit-3-chemistry",
        ])
        for passage in passages:
            self.assertIn("| Glucose | mmol/L |\n| Creatinine | umol/L |", passage["text"])

    def test_version_aware_rank_keeps_comparison_sources(self):
        passages = retrieve(self.study_dir, "Did Visit 3 timing change in version 2?")
        self.assertEqual(passages[0]["id"], "amendment-01:visit-3-timing-amendment")
        ids = [passage["id"] for passage in passages]
        self.assertLess(ids.index("protocol-v2:visit-3-timing"), ids.index("protocol-v1:visit-3-timing"))
        self.assertEqual(passages[0]["version"], "2")

    def test_blood_pressure_abbreviation_matches_the_full_section(self):
        passages = retrieve(self.study_dir, "Was BP required?", 2)
        self.assertEqual([passage["id"] for passage in passages], [
            "protocol-v1:visit-3-blood-pressure", "protocol-v2:visit-3-blood-pressure",
        ])

    def test_source_lookup_preserves_heading_and_filename(self):
        passages = {passage["id"]: passage for passage in load_passages(self.study_dir)}
        self.assertEqual(passages["protocol-v1:visit-3-timing"], {
            "id": "protocol-v1:visit-3-timing",
            "document": "protocol-v1.md",
            "section": "Visit 3 timing",
            "version": "1",
            "text": "Visit 3 occurs 12 to 16 days after randomization.",
        })

    def test_unrelated_question_returns_no_passages(self):
        self.assertEqual(retrieve(self.study_dir, "What is the aspirin dosage in v2?"), [])

    def test_empty_and_duplicate_sections_fail(self):
        path = self.docs / "amendment-01.md"
        for content in (
            "## Empty\n",
            "## First\nOne.\n## First\nTwo.\n",
        ):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "empty or duplicate section"):
                    load_passages(self.study_dir)
