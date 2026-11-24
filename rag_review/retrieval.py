"""Retrieve complete, versioned protocol passages for the bundled study."""

import re
from collections import Counter
from math import log
from pathlib import Path
from typing import TypedDict

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

_SOURCES = (
    ("protocol-v1.md", "1"),
    ("protocol-v2.md", "2"),
    ("amendment-01.md", "2"),
)
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9]+")
_BLOOD_PRESSURE = re.compile(r"\bblood pressure\b")
_VERSION = re.compile(r"\b(?:version\s+|v)([12])\b", re.IGNORECASE)
_STOP_WORDS = frozenset(
    "a an and any are as at be can did do does for from had has have how i in is "
    "it me of on or should show tell that the there they to was were what when "
    "where which who will with would".split()
)
_ALIASES = {
    "amended": "amendment",
    "bp": "bloodpressure",
    "change": "amendment",
    "changes": "amendment",
    "changed": "amendment",
    "laboratory": "chemistry",
    "lab": "chemistry",
    "labs": "chemistry",
    "visits": "visit",
}


class Passage(TypedDict):
    id: str
    document: str
    section: str
    version: str
    text: str


def _documents(study_dir: Path) -> tuple[Document, ...]:
    documents = []
    for filename, version in _SOURCES:
        path = study_dir / "docs" / filename
        markdown = path.read_text(encoding="utf-8")
        headings = tuple(_HEADING.finditer(markdown))
        if not headings:
            raise ValueError(f"{filename} must contain at least one level-two heading")
        section_ids = set()
        for index, heading in enumerate(headings):
            title = heading[1].strip()
            slug = "-".join(_WORD.findall(title.casefold()))
            section_id = f"{path.stem}:{slug}"
            end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
            body = markdown[heading.end():end].strip()
            if not slug or not body or section_id in section_ids:
                raise ValueError(f"{filename} has an empty or duplicate section: {title!r}")
            section_ids.add(section_id)
            documents.append(Document(
                id=section_id,
                page_content=body,
                metadata={"document": filename, "section": title, "version": version},
            ))
    return tuple(documents)


def _terms(text: str) -> set[str]:
    normalized = _BLOOD_PRESSURE.sub("bloodpressure", text.casefold())
    return {
        _ALIASES.get(word, word) for word in _WORD.findall(normalized)
        if word not in _STOP_WORDS
    }


class ProtocolRetriever(BaseRetriever):
    """Rank authored sections by lexical overlap without an embedding service."""

    documents: tuple[Document, ...]
    limit: int = 6

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        versions = set(_VERSION.findall(query))
        query_terms = _terms(_VERSION.sub("", query))
        section_terms = [
            (_terms(doc.metadata["section"]), _terms(doc.page_content))
            for doc in self.documents
        ]
        frequencies = Counter(term for title, body in section_terms for term in title | body)
        weights = {
            term: 1 + log((len(self.documents) + 1) / (frequencies[term] + 1))
            for term in query_terms
        }
        scored = []
        for document, (title, body) in zip(self.documents, section_terms):
            score = sum(weights[term] * 3 for term in sorted(query_terms & title))
            score += sum(weights[term] for term in sorted(query_terms & body))
            if score:
                score += 2 if document.metadata["version"] in versions else 0
                scored.append((score, document))
        scored.sort(key=lambda match: match[0], reverse=True)
        return [document for _, document in scored[:self.limit]]


def _passage(document: Document) -> Passage:
    assert document.id is not None
    return {
        "id": document.id,
        "document": document.metadata["document"],
        "section": document.metadata["section"],
        "version": document.metadata["version"],
        "text": document.page_content,
    }


def load_passages(study_dir: Path) -> list[Passage]:
    """Load passages in source order for looking up reviewed citations."""
    return [_passage(document) for document in _documents(study_dir)]


def retrieve(study_dir: Path, question: str, limit: int = 6) -> list[Passage]:
    """Find protocol passages for a question with stable source identifiers."""
    if limit < 1:
        raise ValueError("Retrieval limit must be positive")
    retriever = ProtocolRetriever(documents=_documents(study_dir), limit=limit)
    return [_passage(document) for document in retriever.invoke(question)]
