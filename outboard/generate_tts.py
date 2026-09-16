# python generate_tts.py
# python generate_tts.py --manifest custom_manifest.txt
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from piper import PiperVoice

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "tts_manifest.txt"
DEFAULT_MODEL = ROOT / "models" / "piper" / "fr_FR-siwis-medium.onnx"
DEFAULT_OUT_DIR = ROOT.parent / "onboard" / "assets" / "tts"


def parse_manifest(path: Path) -> list[tuple[str, str]]:
    entries = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ";" not in line:
            raise ValueError(f"{path}:{lineno}: no ';' separator in {raw!r}")
        filename, content = line.split(";", 1)
        filename, content = filename.strip(), content.strip()
        if not filename or not content:
            raise ValueError(f"{path}:{lineno}: empty filename or content in {raw!r}")
        entries.append((filename, content))
    return entries


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    p.add_argument("--model", default=str(DEFAULT_MODEL))
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = parse_manifest(Path(args.manifest))
    print(f"{len(entries)} entries in {args.manifest}")

    voice = PiperVoice.load(args.model)
    for filename, content in entries:
        chunks = list(voice.synthesize(content))
        sr = chunks[0].sample_rate
        audio = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        out_path = out_dir / f"{filename}.wav"
        sf.write(out_path, audio, sr)
        print(f"  {filename}.wav  <-  {content!r}")

    print(f"\nWrote {len(entries)} files to {out_dir}")


if __name__ == "__main__":
    main()
