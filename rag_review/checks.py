"""Run predefined Visit 3 checks against the study's supplied CSV records."""

import csv
from pathlib import Path

import duckdb

_STATUSES = ("pass", "outside_window", "missing_visit", "missing_result", "cannot_assess")
_SCHEMAS = {
    "subjects": ("USUBJID", "RAND_DATE", "PROTOCOL_VERSION"),
    "sv": ("USUBJID", "VISITNUM", "SVSTDTC"),
    "vs": ("USUBJID", "VISITNUM", "VSTESTCD", "VSORRES"),
    "lb": ("USUBJID", "VISITNUM", "LBTESTCD", "LBORRES"),
}
_CHECKS = {
    "visit3_timing": None,
    "visit3_bp": ("vs", "VSTESTCD", "VSORRES", "bp_codes"),
    "visit3_chemistry": ("lb", "LBTESTCD", "LBORRES", "chemistry_codes"),
}

_TIMING_QUERY = """
    WITH visit_rows AS (
        SELECT u.USUBJID, u.RAND_DATE, u.PROTOCOL_VERSION, s.VISITNUM, s.SVSTDTC,
               CASE WHEN regexp_full_match(trim(u.RAND_DATE), '[0-9]{4}-[0-9]{2}-[0-9]{2}')
                    THEN try_cast(trim(u.RAND_DATE) AS DATE) END AS anchor_date,
               CASE WHEN regexp_full_match(trim(s.SVSTDTC), '[0-9]{4}-[0-9]{2}-[0-9]{2}')
                    THEN try_cast(trim(s.SVSTDTC) AS DATE) END AS actual_date
        FROM subjects AS u
        LEFT JOIN sv AS s ON u.USUBJID = s.USUBJID
            AND try_cast(s.VISITNUM AS DOUBLE) = 3
    ), visit_days AS (
        SELECT *, date_diff('day', anchor_date, actual_date) AS study_day
        FROM visit_rows
    )
    SELECT v.USUBJID, v.RAND_DATE, v.PROTOCOL_VERSION,
           list(struct_pack(USUBJID := v.USUBJID, VISITNUM := VISITNUM, SVSTDTC := SVSTDTC)
                ORDER BY SVSTDTC, VISITNUM) FILTER (WHERE VISITNUM IS NOT NULL) AS visits,
           count(DISTINCT actual_date) AS distinct_dates,
           count(*) FILTER (WHERE VISITNUM IS NOT NULL AND actual_date IS NULL) AS incomplete_dates,
           bool_or(anchor_date IS NOT NULL) AS has_anchor,
           min(study_day) AS study_day,
           bool_and(study_day BETWEEN r.min_day AND r.max_day) AS in_window
    FROM visit_days AS v
    LEFT JOIN reviewed_rules AS r ON trim(v.PROTOCOL_VERSION) = r.version
    GROUP BY v.USUBJID, v.RAND_DATE, v.PROTOCOL_VERSION
    ORDER BY v.USUBJID
"""


def _measurements_query(table, code_column, result_column):
    return f"""
        WITH observations AS (
            SELECT m.USUBJID, m.VISITNUM, m.{code_column}, m.{result_column}
            FROM {table} AS m
            JOIN subjects AS s ON m.USUBJID = s.USUBJID
            WHERE try_cast(m.VISITNUM AS DOUBLE) = 3
        ), recorded_results AS (
            SELECT USUBJID, trim({code_column}) AS code,
                   count(DISTINCT nullif(trim({result_column}), '')) AS distinct_results
            FROM observations
            GROUP BY USUBJID, code
        ), coverage AS (
            SELECT s.USUBJID,
                   list(c.code ORDER BY c.code) FILTER (
                       WHERE coalesce(r.distinct_results, 0) = 0) AS missing_codes,
                   list(c.code ORDER BY c.code) FILTER (
                       WHERE r.distinct_results > 1) AS conflicting_codes
            FROM subjects AS s
            JOIN required_codes AS c ON trim(s.PROTOCOL_VERSION) = c.version
            LEFT JOIN recorded_results AS r ON s.USUBJID = r.USUBJID AND c.code = r.code
            GROUP BY s.USUBJID
        ), evidence AS (
            SELECT USUBJID,
                   list(struct_pack(USUBJID := USUBJID, VISITNUM := VISITNUM,
                                    {code_column} := {code_column}, {result_column} := {result_column})
                        ORDER BY {code_column}, {result_column}, VISITNUM) AS observations
            FROM observations
            GROUP BY USUBJID
        )
        SELECT s.USUBJID, e.observations, c.missing_codes, c.conflicting_codes
        FROM subjects AS s
        LEFT JOIN evidence AS e USING (USUBJID)
        LEFT JOIN coverage AS c USING (USUBJID)
    """


def _load_csv(db, directory, table):
    path = directory / f"{table}.csv"
    columns = _SCHEMAS[table]
    if not path.is_file():
        raise ValueError(f"Required study file is missing: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        headers = next(csv.reader(handle), [])
    if len(set(headers)) != len(headers):
        raise ValueError(f"{path.name} contains duplicate headers.")
    if missing := set(columns) - set(headers):
        raise ValueError(f"{path.name} is missing columns: {', '.join(sorted(missing))}")
    try:
        db.execute(
            f"CREATE TABLE {table} AS SELECT {', '.join(columns)} FROM "
            "read_csv(?, delim=',', header=true, all_varchar=true, strict_mode=true)",
            [str(path.resolve())],
        )
    except duckdb.Error as error:
        raise ValueError(f"{path.name} could not be read as a UTF-8 CSV.") from error


def _prepare_rules(db, rules, measurement):
    versions = rules.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise ValueError("Reviewed rules must include at least one protocol version.")
    windows, codes = [], []
    for version, rule in versions.items():
        if not isinstance(version, str) or not version or version != version.strip():
            raise ValueError("Protocol version identifiers must be nonempty strings.")
        if not isinstance(rule, dict) or rule.get("visitnum") != 3:
            raise ValueError(f"Protocol version {version} must define Visit 3.")
        lower, upper = rule.get("min_day"), rule.get("max_day")
        if type(lower) is not int or type(upper) is not int or lower > upper:
            raise ValueError(f"Protocol version {version} has an invalid day window.")
        windows.append((version, lower, upper))
        if measurement:
            expected = rule.get(measurement[3])
            if (not isinstance(expected, list) or not expected
                    or any(not isinstance(code, str) or not code or code != code.strip() for code in expected)
                    or len(set(expected)) != len(expected)):
                raise ValueError(f"Protocol version {version} has invalid required test codes.")
            codes.extend((version, code) for code in expected)
    db.execute("CREATE TABLE reviewed_rules (version VARCHAR, min_day INTEGER, max_day INTEGER)")
    db.executemany("INSERT INTO reviewed_rules VALUES (?, ?, ?)", windows)
    if measurement:
        db.execute("CREATE TABLE required_codes (version VARCHAR, code VARCHAR)")
        db.executemany("INSERT INTO required_codes VALUES (?, ?)", codes)


def _rows(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _classify(row, rule, measurement, coverage):
    if rule is None:
        return "cannot_assess", "The applicable protocol version is missing or unrecognized."
    if not row["visits"]:
        return "missing_visit", "No matching Visit 3 record is present in the supplied SV data."
    if row["distinct_dates"] > 1:
        return "cannot_assess", "Matching Visit 3 records report more than one date."
    if measurement:
        if coverage["conflicting_codes"]:
            codes = ", ".join(coverage["conflicting_codes"])
            return "cannot_assess", f"Multiple different recorded results for: {codes}."
        if coverage["missing_codes"]:
            codes = ", ".join(coverage["missing_codes"])
            return "missing_result", f"No matching nonblank result for: {codes}."
        return "pass", "The supplied data contain the expected results."
    if row["incomplete_dates"] or not row["has_anchor"]:
        return "cannot_assess", "A complete randomization date and Visit 3 date are required."
    window = f"expected day {rule['min_day']} through {rule['max_day']} inclusive"
    detail = f"Recorded Visit 3 on day {row['study_day']} ({window})."
    return ("pass" if row["in_window"] else "outside_window"), detail


def run_check(study_dir: Path, check_id: str, rules: dict) -> dict:
    """Return per-participant findings grounded in the reviewed rules and source rows."""
    if check_id not in _CHECKS:
        raise ValueError(f"Unknown check: {check_id}")
    study_dir = Path(study_dir)
    measurement = _CHECKS[check_id]
    with duckdb.connect(config={"threads": 1}) as db:
        _load_csv(db, study_dir, "subjects")
        _load_csv(db, study_dir, "sv")
        ambiguous_id = db.execute(
            """
            SELECT USUBJID FROM subjects
            GROUP BY USUBJID
            HAVING USUBJID IS NULL OR trim(USUBJID) = '' OR count(*) > 1
            LIMIT 1
            """
        ).fetchone()
        if ambiguous_id is not None:
            raise ValueError("subjects.csv must contain unique, nonblank USUBJID values.")
        _prepare_rules(db, rules, measurement)
        rows = _rows(db.execute(_TIMING_QUERY))
        coverage = {}
        if measurement:
            _load_csv(db, study_dir, measurement[0])
            coverage = {row["USUBJID"]: row for row in _rows(db.execute(_measurements_query(*measurement[:3])))}

    counts = dict.fromkeys(_STATUSES, 0)
    findings = []
    for row in rows:
        subject_id = row["USUBJID"]
        version = (row["PROTOCOL_VERSION"] or "").strip() or None
        rule = rules["versions"].get(version)
        observations = coverage.get(subject_id)
        status, detail = _classify(row, rule, measurement, observations)
        counts[status] += 1
        evidence = {
            "subject": {field: row[field] for field in _SCHEMAS["subjects"]},
            "sv": row["visits"] or [],
        }
        finding = {"USUBJID": subject_id, "protocol_version": version,
                   "status": status, "detail": detail, "evidence": evidence}
        if measurement:
            evidence[measurement[0]] = observations["observations"] or []
            finding["required_codes"] = rule[measurement[3]] if rule else []
        else:
            finding["study_day"] = (row["study_day"] if row["distinct_dates"] == 1
                                    and not row["incomplete_dates"] else None)
            finding["window"] = [rule["min_day"], rule["max_day"]] if rule else None
        findings.append(finding)

    return {"check_id": check_id, "denominator": len(findings), "counts": counts, "findings": findings}
