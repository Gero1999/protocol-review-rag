import json
from pathlib import Path
import tempfile
import unittest

from rag_review.checks import run_check


_RULES = {
    "versions": {
        "1": {"visitnum": 3, "min_day": 12, "max_day": 16,
              "bp_codes": ["SYSBP", "DIABP"], "chemistry_codes": ["GLUC", "CREAT"]},
        "2": {"visitnum": 3, "min_day": 13, "max_day": 17,
              "bp_codes": ["SYSBP", "DIABP"], "chemistry_codes": ["GLUC", "CREAT"]},
    }
}


class ProtocolChecksTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)

    def write(self, name, data):
        (self.directory / name).write_text(data, encoding="utf-8")

    def test_timing_uses_inclusive_versioned_windows_and_supplied_data(self):
        self.write("subjects.csv", """USUBJID,RAND_DATE,PROTOCOL_VERSION
001,2026-01-01,1
002,2026-01-01,2
003,2026-01-01,
004,2026-01-01,1
005,2026-01-01,1
006,2026-01-01,1
007,2026-01,1
008,2026-01-01,2
""")
        self.write("sv.csv", """USUBJID,VISITNUM,SVSTDTC
001,3,2026-01-13
002,3,2026-01-13
003,3,2026-01-15
004,2,2026-01-15
005,3.0,2026-01
006,3,2026-01-13
006,3,2026-01-14
007,3,2026-01-14
008,3.0,2026-01-18
""")
        report = run_check(self.directory, "visit3_timing", _RULES)
        self.assertEqual(report["denominator"], 8)
        self.assertEqual(report["counts"], {
            "pass": 2, "outside_window": 1, "missing_visit": 1,
            "missing_result": 0, "cannot_assess": 4,
        })
        by_id = {row["USUBJID"]: row for row in report["findings"]}
        self.assertEqual(by_id["001"]["study_day"], 12)
        self.assertEqual(by_id["002"]["window"], [13, 17])
        self.assertEqual(by_id["002"]["status"], "outside_window")
        self.assertEqual(by_id["003"]["evidence"]["sv"][0]["SVSTDTC"], "2026-01-15")
        self.assertIsNone(by_id["006"]["study_day"])
        self.assertEqual(by_id["008"]["study_day"], 17)
        json.dumps(report)

    def test_measurements_separate_absent_visits_missing_results_and_conflicts(self):
        self.write("subjects.csv", """USUBJID,RAND_DATE,PROTOCOL_VERSION
A,2026-01-01,1
B,2026-01-01,1
C,2026-01-01,2
D,2026-01-01,2
E,2026-01-01,2
""")
        self.write("sv.csv", """USUBJID,VISITNUM,SVSTDTC
A,3,2026-01-15
B,3,2026-01-15
D,3,2026-01-15
E,3,2026-01-15
""")
        self.write("vs.csv", """USUBJID,VISITNUM,VSTESTCD,VSORRES
A,3,SYSBP,100
A,3,SYSBP,100
A,3,DIABP,80
B,3,SYSBP,100
B,3,DIABP,
B,4,DIABP,90
C,3,SYSBP,100
C,3,DIABP,90
D,3,SYSBP,100
D,3,SYSBP,105
D,3,DIABP,90
E,3,SYSBP,100
E,3,DIABP,80
""")
        self.write("lb.csv", """USUBJID,VISITNUM,LBTESTCD,LBORRES
A,3,GLUC,88
A,3,CREAT,0.9
B,3,GLUC,90
""")
        bp = run_check(self.directory, "visit3_bp", _RULES)
        self.assertEqual([row["status"] for row in bp["findings"]],
                         ["pass", "missing_result", "missing_visit", "cannot_assess", "pass"])
        self.assertEqual(bp["findings"][1]["detail"], "No matching nonblank result for: DIABP.")
        self.assertEqual(bp["findings"][1]["evidence"]["vs"][0]["VSORRES"], None)
        self.assertEqual(bp["findings"][2]["evidence"]["vs"][0]["VSORRES"], "90")
        chemistry = run_check(self.directory, "visit3_chemistry", _RULES)
        self.assertEqual(chemistry["counts"]["missing_result"], 3)
        self.assertEqual(chemistry["findings"][0]["evidence"]["lb"][0]["LBTESTCD"], "CREAT")

    def test_header_only_domains_and_unrecognized_versions(self):
        self.write("subjects.csv", "USUBJID,RAND_DATE,PROTOCOL_VERSION\nA,2026-01-01,3\n")
        self.write("sv.csv", "USUBJID,VISITNUM,SVSTDTC\n")
        self.write("vs.csv", "USUBJID,VISITNUM,VSTESTCD,VSORRES\n")
        row, = run_check(self.directory, "visit3_bp", _RULES)["findings"]
        self.assertEqual(row["status"], "cannot_assess")
        self.assertEqual(row["protocol_version"], "3")
        self.assertEqual(row["evidence"]["vs"], [])

    def test_bad_schema_and_duplicate_subjects_fail_explicitly(self):
        self.write("subjects.csv", """USUBJID,RAND_DATE,PROTOCOL_VERSION
001,2026-01-01,1
001,2026-01-01,2
""")
        self.write("sv.csv", "USUBJID,VISITNUM,VISIT_DATE\n")
        with self.assertRaisesRegex(ValueError, "sv.csv is missing columns: SVSTDTC"):
            run_check(self.directory, "visit3_timing", _RULES)
        self.write("sv.csv", "USUBJID,VISITNUM,SVSTDTC\n")
        with self.assertRaisesRegex(ValueError, "unique, nonblank USUBJID"):
            run_check(self.directory, "visit3_timing", _RULES)
