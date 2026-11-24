"""Regenerate the original synthetic study CSVs."""

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path


DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "demo" / "study"
HEADERS = {
    "subjects": ("USUBJID", "RAND_DATE", "PROTOCOL_VERSION"),
    "sv": ("USUBJID", "VISITNUM", "SVSTDTC"),
    "vs": ("USUBJID", "VISITNUM", "VSTESTCD", "VSORRES"),
    "lb": ("USUBJID", "VISITNUM", "LBTESTCD", "LBORRES"),
}


def generate(output: Path) -> None:
    rng = random.Random(37)
    rows = {name: [] for name in HEADERS}
    for number in range(1, 31):
        subject = f"SUBJ-{number:03}"
        anchor = date(2025, 1, 10) + timedelta(days=number)
        version = "1" if number % 2 else "2"
        rows["subjects"].append((subject, anchor if number != 5 else "", version if number != 6 else ""))
        if number == 4:
            continue

        # Day 12 is within v1 for SUBJ-001 and outside v2 for SUBJ-002.
        day = {1: 12, 2: 12, 3: 17, 10: 17}.get(number, 14)
        visit_date = (anchor + timedelta(days=day)).isoformat()
        rows["sv"].append((subject, 3, visit_date[:7] if number == 9 else visit_date))
        rows["vs"].append((subject, 3, "SYSBP", rng.randint(105, 135)))
        rows["vs"].append((subject, 3, "DIABP", "" if number == 7 else rng.randint(65, 85)))
        rows["lb"].append((subject, 3, "GLUC", rng.randint(79, 109)))
        # SUBJ-008 has a creatinine result at Visit 2 only.
        rows["lb"].append((subject, 2 if number == 8 else 3, "CREAT", f"{rng.uniform(0.7, 1.1):.2f}"))

    output.mkdir(parents=True, exist_ok=True)
    for name, header in HEADERS.items():
        with (output / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows[name])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    generate(parser.parse_args().output)
