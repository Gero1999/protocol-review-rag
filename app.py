"""Streamlit demo for reviewing protocol requirements against synthetic study data."""

import os
from pathlib import Path

import streamlit as st

from rag_review.workflow import DEFAULT_QUESTION, ask, make_langchain_planner

ROOT = Path(__file__).resolve().parent
STUDY = ROOT / "demo" / "study"
EXAMPLES = (
    "Which Visit 3 records need review?",
    "Which Visit 3 records were outside the window?",
    "Which lab results are expected at Visit 3?",
    "What changed for Visit 3 in protocol version 2?",
)
CHECK_NAMES = {
    "visit3_timing": "Visit timing",
    "visit3_bp": "Blood pressure",
    "visit3_chemistry": "Chemistry",
}
STATUS_LABELS = {
    "pass": "Pass",
    "outside_window": "Outside window",
    "missing_visit": "Missing visit record",
    "missing_result": "Missing result",
    "cannot_assess": "Cannot assess",
}
EVIDENCE_LABELS = {
    "subject": "Study mapping",
    "sv": "Visits (SV)",
    "vs": "Vital signs (VS)",
    "lb": "Laboratory results (LB)",
}


def planner_choice():
    if os.getenv("OPENAI_API_KEY"):
        return st.radio(
            "Question routing",
            ["Offline", "OpenAI"],
            horizontal=True,
            help="The default comparison uses local routing. For other questions, OpenAI interprets "
            "the question using protocol excerpts. The DuckDB checks run locally in either mode.",
        )
    return "Offline"


def submit_example(question: str) -> None:
    st.session_state.question = question
    st.session_state.pending_question = question


def show_examples() -> None:
    with st.container(key="review-examples"):
        st.caption("Try a question")
        for left, right in zip(EXAMPLES[::2], EXAMPLES[1::2]):
            for column, question in zip(st.columns(2), (left, right)):
                column.button(question, on_click=submit_example, args=(question,), width="stretch")


def review_evidence(check: dict, finding: dict, sources: dict) -> None:
    with st.container(key=f"participant-evidence-{check['check_id']}"):
        st.markdown(f"#### {finding['USUBJID']} · {STATUS_LABELS[finding['status']]}")
        st.write(finding["detail"])
        rows_panel, protocol_panel = st.columns((3, 2))
        with rows_panel:
            st.markdown("**Source rows**")
            for domain, records in finding["evidence"].items():
                st.caption(EVIDENCE_LABELS[domain])
                if records:
                    rows = [records] if domain == "subject" else records
                    st.dataframe(rows, hide_index=True, width="stretch")
                else:
                    st.caption("No matching rows in the supplied data.")
            with st.expander("Raw evidence (JSON)"):
                st.json(finding["evidence"], expanded=True)

        with protocol_panel:
            st.markdown("**Protocol reference**")
            source_ids = check["source_ids"]
            source_id = source_ids.get(finding["protocol_version"], source_ids.get("unknown"))
            if source_id:
                source = sources[source_id]
                with st.expander(f"{source['section']} · {source['document']}", expanded=True):
                    st.markdown(source["text"])
            else:
                st.caption("No protocol passage is available for this record.")


def review_check(check: dict, sources: dict) -> None:
    check_id = check["check_id"]
    counts = check["counts"]
    with st.container(key=f"review-metrics-{check_id}"):
        participants = st.columns(4)
        participants[0].metric("Expected", check["denominator"])
        participants[1].metric("Passed", counts["pass"])
        participants[2].metric(
            "Follow up", check["denominator"] - counts["pass"] - counts["cannot_assess"]
        )
        participants[3].metric("Cannot assess", counts["cannot_assess"])

    references = []
    for version, source_id in check["source_ids"].items():
        label = "Unknown version" if version == "unknown" else f"v{version}"
        references.append(f"{label} — {sources[source_id]['section']}")
    if references:
        st.caption("Protocol sources · " + " | ".join(references))

    findings = [finding for finding in check["findings"] if finding["status"] != "pass"]
    if not findings:
        st.success("No records need review for this check.")
        return
    st.markdown("#### Flagged records")
    st.dataframe(
        [
            {
                "Participant": item["USUBJID"],
                "Status": STATUS_LABELS[item["status"]],
                "Protocol version": item["protocol_version"] or "Unknown",
                "Finding": item["detail"],
            }
            for item in findings
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "Participant": st.column_config.TextColumn(width=105),
            "Status": st.column_config.TextColumn(width=145),
            "Protocol version": st.column_config.TextColumn(width=135),
        },
    )
    subject = st.selectbox(
        "Inspect supporting records",
        options=[item["USUBJID"] for item in findings],
        index=None,
        placeholder="Choose a flagged participant",
        key=f"review-{check_id}",
    )
    if subject:
        finding = next(item for item in findings if item["USUBJID"] == subject)
        review_evidence(check, finding, sources)


def review_result(result: dict) -> None:
    with st.container(key="review-summary"):
        st.subheader("Review summary")
        st.caption(result["question"])
        if result["status"] != "answered":
            st.info(result["answer"])
        else:
            st.markdown(result["answer"])

    sources = {source["id"]: source for source in result["sources"]}
    if result["checks"]:
        with st.container(key="review-records"):
            st.subheader("Record review")
            tabs = st.tabs([CHECK_NAMES[check["check_id"]] for check in result["checks"]])
            for tab, check in zip(tabs, result["checks"]):
                with tab:
                    review_check(check, sources)

    if sources:
        with st.container(key="review-sources"):
            st.subheader("Protocol sources")
            for source in sources.values():
                label = f"v{source['version']} · {source['section']} · {source['document']}"
                with st.expander(label):
                    st.markdown(source["text"])


def main() -> None:
    st.set_page_config(page_title="Protocol alignment review", layout="wide")
    st.html(ROOT / "styles" / "review.css")
    with st.container(key="review-header"):
        st.caption("Synthetic clinical study")
        st.title("Protocol alignment review")
        st.write("Compare Visit 3 timing, blood pressure, and chemistry with the applicable protocol.")

    with st.container(key="review-intake"):
        mode = planner_choice()
        st.session_state.setdefault("question", DEFAULT_QUESTION)
        with st.form("study-question", border=False):
            field, action = st.columns((4, 1), vertical_alignment="bottom")
            question = field.text_input(
                "Ask about the study",
                value=None,
                key="question",
                placeholder=DEFAULT_QUESTION,
                max_chars=500,
            )
            submitted = action.form_submit_button("Review study", type="primary", width="stretch")
        show_examples()

    pending = st.session_state.pop("pending_question", None)
    requested = (question or "").strip() if submitted else pending
    if submitted and not requested:
        st.warning("Enter a question or choose an example.")
    if requested:
        st.session_state.pop("review_result", None)
        try:
            planner = None
            if mode == "OpenAI":
                from langchain_openai import ChatOpenAI

                planner = make_langchain_planner(
                    ChatOpenAI(model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini", max_retries=1, timeout=20)
                )
            with st.spinner("Reviewing the study…"):
                st.session_state.review_result = ask(STUDY, requested, planner=planner)
        except (ImportError, OSError, RuntimeError, ValueError):
            st.error("The study review could not run. Check the study files and planner setup.")
    if "review_result" in st.session_state:
        review_result(st.session_state.review_result)


if __name__ == "__main__":
    main()
