"""Streamlit demo for reviewing protocol requirements against synthetic study data."""

import os
from pathlib import Path

import streamlit as st

from rag_review.workflow import ask, make_langchain_planner

STUDY = Path(__file__).resolve().parent / "demo" / "study"
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


def planner_choice():
    if os.getenv("OPENAI_API_KEY"):
        return st.radio(
            "Question routing",
            ["Offline", "OpenAI"],
            horizontal=True,
            help="Offline uses local retrieval and rules. OpenAI interprets the question using "
            "protocol excerpts. The DuckDB checks run locally in either mode.",
        )
    return "Offline"


def submit_example(question: str) -> None:
    st.session_state.question = question
    st.session_state.pending_question = question


def show_examples() -> None:
    st.caption("Try a question")
    for left, right in zip(EXAMPLES[::2], EXAMPLES[1::2]):
        for column, question in zip(st.columns(2), (left, right)):
            column.button(question, on_click=submit_example, args=(question,), width="stretch")


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
    st.dataframe(
        [
            {
                "Participant": item["USUBJID"],
                "Protocol version": item["protocol_version"] or "Unknown",
                "Status": STATUS_LABELS[item["status"]],
                "Finding": item["detail"],
            }
            for item in findings
        ],
        hide_index=True,
        width="stretch",
    )
    subject = st.selectbox(
        "Inspect supporting records",
        options=[item["USUBJID"] for item in findings],
        index=None,
        placeholder="Choose a flagged participant",
        key=f"review-{check_id}",
    )
    if subject:
        item = next(item for item in findings if item["USUBJID"] == subject)
        st.write(item["detail"])
        st.json(item["evidence"], expanded=True)


def review_result(result: dict) -> None:
    st.subheader(result["question"])
    if result["status"] != "answered":
        st.info(result["answer"])
    else:
        st.markdown(result["answer"])

    sources = {source["id"]: source for source in result["sources"]}
    if result["checks"]:
        st.subheader("Record review")
        tabs = st.tabs([CHECK_NAMES[check["check_id"]] for check in result["checks"]])
        for tab, check in zip(tabs, result["checks"]):
            with tab:
                review_check(check, sources)

    if sources:
        st.subheader("Protocol sources")
        for source in sources.values():
            label = f"v{source['version']} · {source['section']} · {source['document']}"
            with st.expander(label):
                st.markdown(source["text"])


def main() -> None:
    st.set_page_config(page_title="Protocol alignment review", layout="wide")
    st.html("""
        <style>
        .stMainBlockContainer { max-width: 70rem; padding-top: 3.25rem; }
        [data-testid="stMetric"] {
            border: 1px solid #cfddd5;
            border-radius: .6rem;
            padding: .8rem 1rem;
            background: #f0f5f1;
        }
        @media (max-width: 700px) {
            .stMainBlockContainer { padding-top: 2.25rem; }
            [data-testid="stMetric"] { padding: .55rem; }
            [class*="st-key-review-metrics-"] [data-testid="stHorizontalBlock"] {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: .5rem;
            }
            [class*="st-key-review-metrics-"] [data-testid="stColumn"] {
                width: 100%;
                min-width: 0;
            }
        }
        </style>
    """)
    st.title("Protocol alignment review")
    st.write("Compare the study protocol with recorded visits, vital signs, and lab results.")
    st.caption("Demo study · Synthetic records · Visit 3")
    mode = planner_choice()

    with st.form("study-question"):
        question = st.text_input(
            "Ask about the study",
            key="question",
            placeholder="Which Visit 3 records need review?",
            max_chars=500,
        )
        submitted = st.form_submit_button("Review study", type="primary")
    show_examples()

    pending = st.session_state.pop("pending_question", None)
    requested = question.strip() if submitted else pending
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
