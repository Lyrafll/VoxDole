# Compose a spoken callsign at runtime by concatenating pre-generated
# phonetic-alphabet/digit clips from assets/tts/.
#
# python -m tts.compose HB9EGM
# python -m tts.compose HB9EGM --play
# python -m tts.compose HB9EGM --out hb9egm.wav
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets" / "tts"

# letter -> clip filename (matches tts_manifest.txt)
LETTER_WORD = {
    "A": "alpha", "B": "bravo", "C": "charlie", "D": "delta", "E": "echo",
    "F": "foxtrot", "G": "golf", "H": "hotel", "I": "india", "J": "juliet",
    "K": "kilo", "L": "lima", "M": "mike", "N": "november", "O": "oscar",
    "P": "papa", "Q": "quebec", "R": "romeo", "S": "sierra", "T": "tango",
    "U": "uniform", "V": "victor", "W": "whiskey", "X": "xray",
    "Y": "yankee", "Z": "zulu",
}


def _filename_for(char: str) -> str:
    char = char.upper()
    if char.isdigit():
        return f"digit_{char}"
    if char in LETTER_WORD:
        return LETTER_WORD[char]
    raise ValueError(f"no TTS clip for character {char!r} -- only A-Z and 0-9 are composable")


def load_clip(name: str, assets_dir: Path = ASSETS_DIR) -> tuple[np.ndarray, int]:
    return sf.read(assets_dir / f"{name}.wav", dtype="float32")


def concat(*clips: tuple[np.ndarray, int], pause_ms: float = 80.0) -> tuple[np.ndarray, int]:
    sr = clips[0][1]
    for _, clip_sr in clips:
        if clip_sr != sr:
            raise ValueError(f"sample rate mismatch: {clip_sr} vs {sr}")

    pause = np.zeros(int(sr * pause_ms / 1000), dtype="float32")
    pieces = []
    for i, (audio, _) in enumerate(clips):
        if i > 0:
            pieces.append(pause)
        pieces.append(audio)
    return np.concatenate(pieces), sr


def compose(text: str, pause_ms: float = 40.0, assets_dir: Path = ASSETS_DIR) -> tuple[np.ndarray, int]:
    """Concatenate one clip per char in `text` (letters/digits only,
    everything else skipped), with a short silence gap between each.
    Returns (samples, sample_rate).
    """
    chars = [c for c in text if c.isalnum()]
    if not chars:
        raise ValueError(f"nothing composable in {text!r}")

    clips = []
    sr = None
    for char in chars:
        path = assets_dir / f"{_filename_for(char)}.wav"
        if not path.exists():
            raise FileNotFoundError(f"missing clip for {char!r}: {path} (run generate_tts.py first)")
        audio, file_sr = sf.read(path, dtype="float32")
        if sr is None:
            sr = file_sr
        elif file_sr != sr:
            raise ValueError(f"{path} is {file_sr} Hz, expected {sr} Hz -- regenerate all clips with the same voice")
        clips.append(audio)

    pause = np.zeros(int(sr * pause_ms / 1000), dtype="float32")
    pieces = []
    for i, clip in enumerate(clips):
        if i > 0:
            pieces.append(pause)
        pieces.append(clip)
    return np.concatenate(pieces), sr


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text", help="callsign to compose, e.g. HB9EGM")
    p.add_argument("--pause-ms", type=float, default=40.0)
    p.add_argument("--out", default=None, help="write the composed WAV here")
    p.add_argument("--play", action="store_true", help="play back through the default audio device")
    args = p.parse_args()

    audio, sr = compose(args.text, pause_ms=args.pause_ms)
    print(f"composed {args.text!r}: {len(audio) / sr:.2f}s at {sr} Hz")

    if args.out:
        sf.write(args.out, audio, sr)
        print(f"wrote {args.out}")

    if args.play or not args.out:
        import sounddevice as sd
        sd.play(audio, sr)
        sd.wait()


if __name__ == "__main__":
    main()
