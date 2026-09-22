from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

import vosk

vosk.SetLogLevel(-1)


class VoskEngine:
    def __init__(self, model_path: Path, sample_rate: int = 16000,
                 grammar: Optional[Sequence[str]] = None, min_confidence: float = 0.0):
        self.model_path = Path(model_path)
        self.sample_rate = sample_rate
        self.grammar = list(grammar) if grammar else None
        self.min_confidence = min_confidence
        self._model: Optional[vosk.Model] = None

    def load(self) -> None:
        self._model = vosk.Model(str(self.model_path))

    def new_recognizer(self) -> vosk.KaldiRecognizer:
        assert self._model is not None, "call load() first"
        if self.grammar:
            grammar_json = json.dumps(self.grammar + ["[unk]"], ensure_ascii=False)
            rec = vosk.KaldiRecognizer(self._model, self.sample_rate, grammar_json)
        else:
            rec = vosk.KaldiRecognizer(self._model, self.sample_rate)
        rec.SetWords(True)
        return rec

    def result_text(self, result: dict) -> str:
        words = result.get("result")
        if words is None:
            return result.get("text", "")
        parts = []
        for w in words:
            word = w["word"]
            if word == "[unk]":
                parts.append(word)
            elif w["conf"] < self.min_confidence:
                parts.append(f"[{word}]")
            else:
                parts.append(word)
        return " ".join(parts)
