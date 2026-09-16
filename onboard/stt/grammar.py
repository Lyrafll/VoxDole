from __future__ import annotations

from scoring import WORD_TO_TOKEN
from stt.vocabulary import CONTEXT_WORDS


def identifier_grammar() -> list[str]:
    return sorted(WORD_TO_TOKEN.keys()) + sorted(CONTEXT_WORDS)
