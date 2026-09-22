# python -m relay --keyboard
# python -m relay --qso /dev/gpiochip2 10 --wake /dev/gpiochip0 4
from __future__ import annotations

import argparse

import abc
import threading
import time
from typing import Callable

import gpiod
from gpiod.line import Bias, Direction, Edge

QsoCallback = Callable[[bool], None]
EdgeCallback = Callable[[], None]


class RelaySignalSource(abc.ABC):
    def __init__(self) -> None:
        self._qso_callbacks: list[QsoCallback] = []
        self._wake_callbacks: list[EdgeCallback] = []
        self._sleep_callbacks: list[EdgeCallback] = []

    def on_qso(self, callback: QsoCallback) -> None:
        self._qso_callbacks.append(callback)

    def on_wake(self, callback: EdgeCallback) -> None:
        self._wake_callbacks.append(callback)

    def on_sleep(self, callback: EdgeCallback) -> None:
        self._sleep_callbacks.append(callback)

    def _fire_qso(self, is_open: bool) -> None:
        for cb in self._qso_callbacks:
            cb(is_open)

    def _fire_wake(self) -> None:
        for cb in self._wake_callbacks:
            cb()

    def _fire_sleep(self) -> None:
        for cb in self._sleep_callbacks:
            cb()

    @abc.abstractmethod
    def start(self) -> None:
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        ...


class KeyboardRelaySignalSource(RelaySignalSource):
    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        print("KeyboardRelaySignalSource: type QSOON / QSOOFF / OPEN1 / OISIF (Ctrl+C to stop)")
        while not self._stop_flag.is_set():
            try:
                line = input().strip().upper()
            except EOFError:
                break
            if line == "QSOON":
                print("  QSO -> OPEN")
                self._fire_qso(True)
            elif line == "QSOOFF":
                print("  QSO -> CLOSED")
                self._fire_qso(False)
            elif line == "OPEN1":
                print("  relay -> OPEN1 (waking up)")
                self._fire_wake()
            elif line == "OISIF":
                print("  relay -> OISIF (shutting down)")
                self._fire_sleep()
            elif line:
                print(f"  (ignored {line!r} -- type QSOON, QSOOFF, OPEN1, or OISIF)")

    def stop(self) -> None:
        self._stop_flag.set()


GpioLine = tuple[str, int]  # (chip path, line offset)


class GpioRelaySignalSource(RelaySignalSource):
    def __init__(self, qso: GpioLine, wake: GpioLine | None = None, sleep: GpioLine | None = None,
                 debounce_ms: float = 20.0) -> None:
        super().__init__()
        self.debounce_s = debounce_ms / 1000.0
        self._targets: dict[GpioLine, str] = {qso: "qso"}
        if wake is not None:
            self._targets[wake] = "wake"
        if sleep is not None:
            self._targets[sleep] = "sleep"
        self._requests = []
        self._threads: list[threading.Thread] = []
        self._stop_flag = threading.Event()

    def start(self) -> None:
        settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP, edge_detection=Edge.BOTH)
        by_chip: dict[str, dict[int, str]] = {}
        for (chip, line), kind in self._targets.items():
            by_chip.setdefault(chip, {})[line] = kind

        for chip, lines_kinds in by_chip.items():
            request = gpiod.request_lines(
                chip, consumer="voxdole-relay",
                config={line: settings for line in lines_kinds},
            )
            self._requests.append(request)
            thread = threading.Thread(target=self._loop, args=(request, lines_kinds), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _loop(self, request, lines_kinds: dict[int, str]) -> None:
        pending: dict[int, bool] = {}
        while not self._stop_flag.is_set():
            if request.wait_edge_events(timeout=self.debounce_s):
                for event in request.read_edge_events():
                    pending[event.line_offset] = event.event_type.name == "FALLING_EDGE"
                continue

            for offset, pressed in pending.items():
                kind = lines_kinds[offset]
                if kind == "qso":
                    self._fire_qso(pressed)
                elif kind == "wake" and pressed:
                    self._fire_wake()
                elif kind == "sleep" and pressed:
                    self._fire_sleep()
            pending.clear()

    def stop(self) -> None:
        self._stop_flag.set()
        for thread in self._threads:
            thread.join(timeout=1.0)
        for request in self._requests:
            request.release()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--keyboard", action="store_true", help="use KeyboardRelaySignalSource for a standalone test")
    p.add_argument("--qso", nargs=2, metavar=("CHIP", "LINE"), help="QSO line -- required for a GPIO test")
    p.add_argument("--wake", nargs=2, metavar=("CHIP", "LINE"), help="OPEN1 (wake) line -- optional")
    p.add_argument("--sleep", nargs=2, metavar=("CHIP", "LINE"), help="OISIF (sleep) line -- optional")
    args = p.parse_args()

    if args.qso:
        qso = (args.qso[0], int(args.qso[1]))
        wake = (args.wake[0], int(args.wake[1])) if args.wake else None
        sleep = (args.sleep[0], int(args.sleep[1])) if args.sleep else None
        source = GpioRelaySignalSource(qso=qso, wake=wake, sleep=sleep)
    elif args.keyboard:
        source = KeyboardRelaySignalSource()
    else:
        p.print_help()
        return

    source.on_qso(lambda is_open: print(f"  [callback fired] qso is_open={is_open}"))
    source.on_wake(lambda: print("  [callback fired] wake"))
    source.on_sleep(lambda: print("  [callback fired] sleep"))
    source.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        source.stop()
        print("\nstopped.")


if __name__ == "__main__":
    main()
