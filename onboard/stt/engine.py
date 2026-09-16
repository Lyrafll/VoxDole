from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator, Optional, Sequence

import soundfile as sf
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

    def transcribe_file(self, wav_path: Path) -> str:
        data, sr = sf.read(wav_path, dtype="int16", always_2d=False)
        if sr != self.sample_rate:
            raise ValueError(f"{wav_path} is {sr} Hz, engine configured for {self.sample_rate} Hz")
        rec = self.new_recognizer()
        pcm_bytes = data.tobytes()
        chunk = 4000
        for i in range(0, len(pcm_bytes), chunk):
            rec.AcceptWaveform(pcm_bytes[i:i + chunk])
        return self.result_text(json.loads(rec.FinalResult()))

    def transcribe_stream(self, frames: Iterator[bytes], sample_rate: int) -> Iterator[str]:
        if sample_rate != self.sample_rate:
            raise ValueError(f"stream is {sample_rate} Hz, engine expects {self.sample_rate} Hz")
        rec = self.new_recognizer()
        for frame in frames:
            if rec.AcceptWaveform(frame):
                text = self.result_text(json.loads(rec.Result()))
                if text:
                    yield f"[final] {text}"
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "")
                if partial:
                    yield f"[partial] {partial}"
        text = self.result_text(json.loads(rec.FinalResult()))
        if text:
            yield f"[final] {text}"
