from __future__ import annotations

import argparse
import json
import queue
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd

import config
from relay import GpioRelaySignalSource, KeyboardRelaySignalSource
from stt.engine import VoskEngine
from stt.grammar import identifier_grammar
from storage.db import add_message, connect, get_pending_messages, mark_delivered
from storage.files import load_message_audio, save_message_audio
from workflow.state_machine import Workflow

SQUELCH_OPEN = object()
SQUELCH_CLOSE = object()


def find_output_device(name_substr: str) -> int:
    needle = name_substr.lower()
    for i, dev in enumerate(sd.query_devices()):
        if needle in dev["name"].lower() and dev["max_output_channels"] > 0:
            return i
    raise RuntimeError(f"no output device matching {name_substr!r} -- run --list-devices")


def find_input_device(name_substr: str) -> int:
    needle = name_substr.lower()
    for i, dev in enumerate(sd.query_devices()):
        if needle in dev["name"].lower() and dev["max_input_channels"] > 0:
            return i
    raise RuntimeError(f"no input device matching {name_substr!r} -- run --list-devices")


def target_samplerate(device) -> float:
    info = sd.query_devices(device) if device is not None else sd.query_devices(kind="output")
    return info["default_samplerate"]


def resample(audio: np.ndarray, orig_sr: int, target_sr: float) -> np.ndarray:
    duration = len(audio) / orig_sr
    n_new = int(round(duration * target_sr))
    x_old = np.linspace(0, duration, len(audio))
    x_new = np.linspace(0, duration, n_new)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--device", type=int, default=None)
    p.add_argument("--input-device-name", default=None,
                    help="match the input device by name substring instead of a fixed index -- "
                         "overrides --device if given")
    p.add_argument("--output-device", type=int, default=None)
    p.add_argument("--output-device-name", default=None,
                    help="match the output device by name substring instead of a fixed index -- "
                         "overrides --output-device if given")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--relay-signal", choices=["keyboard", "gpio"], default="keyboard",
                    help="relay signal source -- 'keyboard' (type QSOON/QSOOFF/OPEN1/OISIF, default) "
                         "or 'gpio' (the real relay pins, requires --relay-qso-chip and --relay-qso-line)")
    p.add_argument("--relay-qso-chip", default=None, help="e.g. /dev/gpiochip2 -- required if --relay-signal gpio")
    p.add_argument("--relay-qso-line", type=int, default=None, help="QSO (squelch) line offset")
    p.add_argument("--relay-wake-chip", default=None, help="optional -- OPEN1 (wake) chip")
    p.add_argument("--relay-wake-line", type=int, default=None, help="optional -- OPEN1 (wake) line offset")
    p.add_argument("--relay-sleep-chip", default=None, help="optional -- OISIF (sleep) chip")
    p.add_argument("--relay-sleep-line", type=int, default=None, help="optional -- OISIF (sleep) line offset")
    args = p.parse_args()

    if args.relay_signal == "gpio" and (args.relay_qso_chip is None or args.relay_qso_line is None):
        p.error("--relay-signal gpio requires --relay-qso-chip and --relay-qso-line")
    if (args.relay_wake_chip is None) != (args.relay_wake_line is None):
        p.error("--relay-wake-chip and --relay-wake-line must be given together")
    if (args.relay_sleep_chip is None) != (args.relay_sleep_line is None):
        p.error("--relay-sleep-chip and --relay-sleep-line must be given together")

    if args.list_devices:
        print(sd.query_devices())
        return

    input_device = args.device
    if args.input_device_name:
        input_device = find_input_device(args.input_device_name)
        print(f"--input-device-name {args.input_device_name!r} -> resolved to device index {input_device}")

    output_device = args.output_device
    if args.output_device_name:
        output_device = find_output_device(args.output_device_name)
        print(f"--output-device-name {args.output_device_name!r} -> resolved to device index {output_device}")

    output_rate = target_samplerate(output_device)

    db = connect(config.DB_PATH)

    def reply(audio: np.ndarray, sr: int) -> None:
        # resampling here is needed for the PRO headset raw output, which
        # only accepts 44100Hz. Tho may or may not still be needed once this
        # runs against the real I2S pins
        # TODO : potentially adapt to the new way to reply (no headset, but a speaker)
        if sr != output_rate:
            audio = resample(audio, sr, output_rate)
            sr = output_rate
        if audio.ndim == 1:
            audio = np.column_stack([audio, audio])
        sd.play(audio, sr, device=output_device)
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

    workflow = Workflow(reply=reply, save_message=save_message, fetch_messages=fetch_messages, on_state_change=on_state_change)

    q: "queue.Queue" = queue.Queue()

    def on_squelch(is_open: bool) -> None:
        q.put(SQUELCH_OPEN if is_open else SQUELCH_CLOSE)
        if is_open:
            workflow.on_squelch(True)

    def on_relay_wake() -> None:
        print("[RELAY] woke up (OPEN1)")
        workflow.on_relay_wake()

    def on_relay_sleep() -> None:
        print("[RELAY] shut down (OISIF)")
        workflow.on_relay_sleep()

    if args.relay_signal == "gpio":
        wake = (args.relay_wake_chip, args.relay_wake_line) if args.relay_wake_chip else None
        sleep = (args.relay_sleep_chip, args.relay_sleep_line) if args.relay_sleep_chip else None
        relay_source = GpioRelaySignalSource(qso=(args.relay_qso_chip, args.relay_qso_line), wake=wake, sleep=sleep)
    else:
        relay_source = KeyboardRelaySignalSource()
    relay_source.on_qso(on_squelch)
    relay_source.on_wake(on_relay_wake)
    relay_source.on_sleep(on_relay_sleep)
    relay_source.start()

    engine = VoskEngine(config.VOSK_MODEL_PATH, grammar=identifier_grammar(), min_confidence=config.MIN_CONFIDENCE)
    print("Loading vosk-grammar ...")
    engine.load()

    def audio_callback(indata, frames, time_info, status) -> None:
        if status:
            print(status)
        frame = bytes(indata)
        workflow.on_audio_frame(frame)
        q.put(frame)

    recognizer = engine.new_recognizer()
    listening = False

    print("Ready. STT only runs while QSO is on.\n")
    with sd.RawInputStream(
        samplerate=config.SAMPLE_RATE, blocksize=4000, device=input_device,
        dtype="int16", channels=1, callback=audio_callback,
    ):
        try:
            while True:
                item = q.get()

                if item is SQUELCH_OPEN:
                    if workflow.stt_needed():
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
                    workflow.on_squelch(False)
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
