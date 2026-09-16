from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd

import config
from audio.gate import GpioSquelchSource, KeyboardSquelchSource
from stt.engine import VoskEngine
from stt.grammar import identifier_grammar
from storage.db import add_message, connect, get_pending_messages, mark_delivered
from storage.files import load_message_audio, save_message_audio
from workflow.state_machine import Workflow

SQUELCH_OPEN = object()
SQUELCH_CLOSE = object()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--device", type=int, default=None)
    p.add_argument("--output-device", type=int, default=None)
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--squelch", choices=["keyboard", "gpio"], default="keyboard",
                    help="squelch signal source -- 'keyboard' (type QSOON/QSOOFF, default) "
                         "or 'gpio' (a physical button, requires --gpio-chip and --gpio-line)")
    p.add_argument("--gpio-chip", default=None, help="e.g. /dev/gpiochip0 -- required if --squelch gpio")
    p.add_argument("--gpio-line", type=int, default=None, help="line offset -- required if --squelch gpio")
    args = p.parse_args()

    if args.squelch == "gpio" and (args.gpio_chip is None or args.gpio_line is None):
        p.error("--squelch gpio requires both --gpio-chip and --gpio-line")

    if args.list_devices:
        print(sd.query_devices())
        return

    db = connect(config.DB_PATH)

    def reply(audio: np.ndarray, sr: int) -> None:
        sd.play(audio, sr, device=args.output_device)
        sd.wait()

    def save_message(caller: str, receiver: str, audio_bytes: bytes) -> None:
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        recorded_at = datetime.now(timezone.utc)
        path = save_message_audio(caller, receiver, recorded_at, audio, config.SAMPLE_RATE,
                                   base_dir=config.MESSAGES_DIR)
        message_id = add_message(db, caller, receiver, audio_path=str(path), recorded_at=recorded_at.isoformat())
        print(f"[STORING] message {message_id}: {caller} -> {receiver} ({path})")

    def fetch_messages(callsign: str) -> list[tuple[str, np.ndarray]]:
        pending = get_pending_messages(db, callsign)
        result = []
        for row in pending:
            audio, _ = load_message_audio(Path(row["audio_path"]))
            result.append((row["sender_callsign"], audio))
            mark_delivered(db, row["id"])
        print(f"[ANNOUNCING] {len(result)} message(s) for {callsign}")
        return result

    def on_state_change(state) -> None:
        print(f"[STATE] {state.name} (caller={workflow.caller_callsign}, receiver={workflow.receiver_callsign})")

    def on_timeout(state) -> None:
        print(f"[TIMEOUT] no response in {state.name} (caller={workflow.caller_callsign}, "
              f"receiver={workflow.receiver_callsign}) -- resetting to IDLE")

    workflow = Workflow(reply=reply, save_message=save_message, fetch_messages=fetch_messages,
                         on_state_change=on_state_change, on_timeout=on_timeout)

    q: "queue.Queue" = queue.Queue()

    def on_squelch(is_open: bool) -> None:
        q.put(SQUELCH_OPEN if is_open else SQUELCH_CLOSE)
        workflow.on_squelch(is_open)

    if args.squelch == "gpio":
        squelch = GpioSquelchSource(chip=args.gpio_chip, line=args.gpio_line)
    else:
        squelch = KeyboardSquelchSource()
    squelch.on_change(on_squelch)
    squelch.start()

    engine = VoskEngine(config.VOSK_MODEL_PATH, grammar=identifier_grammar(), min_confidence=config.MIN_CONFIDENCE)
    print("Loading vosk-grammar ...")
    engine.load()

    def audio_callback(indata, frames, time_info, status) -> None:
        if status:
            print(status)
        frame = bytes(indata)
        workflow.on_audio_frame(frame)
        q.put(frame)

    def timeout_loop() -> None:
        while True:
            time.sleep(1.0)
            workflow.tick()

    threading.Thread(target=timeout_loop, daemon=True).start()

    recognizer = engine.new_recognizer()
    listening = False

    print("Ready. STT only runs while QSO is on.\n")
    with sd.RawInputStream(
        samplerate=config.SAMPLE_RATE, blocksize=4000, device=args.device,
        dtype="int16", channels=1, callback=audio_callback,
    ):
        try:
            while True:
                item = q.get()

                if item is SQUELCH_OPEN:
                    recognizer.Reset()
                    listening = True
                    continue

                if item is SQUELCH_CLOSE:
                    if listening:
                        text = engine.result_text(json.loads(recognizer.FinalResult()))
                        if text:
                            print(f"[final] {text}")
                            workflow.on_final_result(text)
                        listening = False
                    continue

                if not listening:
                    continue
                if recognizer.AcceptWaveform(item):
                    text = engine.result_text(json.loads(recognizer.Result()))
                    if text:
                        print(f"[final] {text}")
                        workflow.on_final_result(text)
                else:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "")
                    if partial:
                        print(f"[partial] {partial}")
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
