"""Shared matcher: does a stored memory entry point at a deleted document?

The memory tables carry no document foreign key, so an entry that "points to" a
document is recognised from its text: the document id (word-bounded, so "12"
does not match "120") or, when the caller knows it, the document name. The same
matcher is used by the PostgreSQL and the in-memory fallback paths, so a purge
behaves identically with or without a database.
"""

import re
from typing import Iterable, List, Optional

# Characters that count as part of a word — a document id must not match inside
# a longer token ("7" must not match "70" or "doc7x").
_WORD_CHARS = "0-9A-Za-z_"


def document_needles(
    document_id: Optional[str], document_name: Optional[str] = ""
) -> List[str]:
    """Normalised needles to look for, most specific last (id first)."""
    needles: List[str] = []
    for raw in (document_id, document_name):
        needle = str(raw or "").strip().lower()
        if needle and needle not in needles:
            needles.append(needle)
    return needles


def references_document(text: Optional[str], needles: Iterable[str]) -> bool:
    """True when `text` mentions any of the document needles as a whole token."""
    if not text:
        return False
    lowered = text.lower()
    for needle in needles:
        if not needle:
            continue
        pattern = rf"(?<![{_WORD_CHARS}]){re.escape(needle)}(?![{_WORD_CHARS}])"
        if re.search(pattern, lowered):
            return True
    return False


def postgres_reference_pattern(needle: str) -> str:
    """PostgreSQL ARE equivalent of references_document (no lookaround)."""
    escaped = re.sub(r"([\\^$.|?*+()\[\]{}])", r"\\\1", needle)
    return rf"\m{escaped}\M"
