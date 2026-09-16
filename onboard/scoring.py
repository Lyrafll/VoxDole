from __future__ import annotations

import re
import unicodedata

from stt.vocabulary import DIGIT_WORDS, PHONETIC

WORD_TO_TOKEN: dict[str, str] = {}
for letter, words in PHONETIC.items():
    for w in words:
        WORD_TO_TOKEN[w.lower()] = letter
for digit, word in enumerate(DIGIT_WORDS):
    WORD_TO_TOKEN[word.lower()] = str(digit)

MIN_RUN_LEN = 2  # a single stray mapped word isn't a callsign


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


_EXCLUDED_TOKEN = "excludedmarker"


def _tokenize(text: str) -> list[str]:
    # bracketed = excluded (low confidence, or "[unk]"); replaced with a
    # placeholder rather than deleted, so it still breaks a run instead of
    # letting two callsigns merge across it
    text = re.sub(r"\[[^\]]*\]", f" {_EXCLUDED_TOKEN} ", text)
    folded = fold(text)
    folded = re.sub(r"[^a-z0-9\s'\-]", " ", folded)
    return [t for t in re.split(r"[\s'\-]+", folded) if t]


def _resolve(tok: str) -> str | None:
    if len(tok) == 1 and tok.isdigit():
        return tok
    return WORD_TO_TOKEN.get(tok)


def extract_callsigns(text: str, min_run_len: int = MIN_RUN_LEN) -> list[str]:
    tokens = _tokenize(text)
    runs: list[str] = []
    current: list[str] = []
    for tok in tokens:
        mapped = _resolve(tok)
        if mapped is not None:
            current.append(mapped)
        else:
            if len(current) >= min_run_len:
                runs.append("".join(current).upper())
            current = []
    if len(current) >= min_run_len:
        runs.append("".join(current).upper())
    return runs
