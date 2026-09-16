# Audio file storage for recorded messages.
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MESSAGES_DIR = ROOT / "messages"


def message_filename(caller: str, receiver: str, recorded_at: datetime) -> str:
    timestamp = recorded_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{caller}_{receiver}_{timestamp}.wav"


def save_message_audio(caller: str, receiver: str, recorded_at: datetime, audio: np.ndarray,
                        sample_rate: int, base_dir: Path = DEFAULT_MESSAGES_DIR) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / message_filename(caller, receiver, recorded_at)
    sf.write(path, audio, sample_rate)
    return path


def load_message_audio(path: Path) -> tuple[np.ndarray, int]:
    return sf.read(path, dtype="float32")


def delete_message_audio(path: Path) -> None:
    Path(path).unlink(missing_ok=True)
