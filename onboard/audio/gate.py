# python -m audio.gate --keyboard
# python -m audio.gate --gpio /dev/gpiochip0 17
from __future__ import annotations

import abc
import threading
import time
from typing import Callable

SquelchCallback = Callable[[bool], None]


class SquelchSource(abc.ABC):
    def __init__(self) -> None:
        self._callbacks: list[SquelchCallback] = []

    def on_change(self, callback: SquelchCallback) -> None:
        self._callbacks.append(callback)

    def _fire(self, is_open: bool) -> None:
        for cb in self._callbacks:
            cb(is_open)

    @abc.abstractmethod
    def start(self) -> None:
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        ...


class KeyboardSquelchSource(SquelchSource):
    def __init__(self) -> None:
        super().__init__()
        self.is_open = False
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        print("KeyboardSquelchSource: type QSOON / QSOOFF (Ctrl+C to stop)")
        while not self._stop_flag.is_set():
            try:
                line = input().strip().upper()
            except EOFError:
                break
            if line == "QSOON":
                self.is_open = True
                print("  squelch -> OPEN (QSO started)")
                self._fire(True)
            elif line == "QSOOFF":
                self.is_open = False
                print("  squelch -> CLOSED (QSO ended)")
                self._fire(False)
            elif line:
                print(f"  (ignored {line!r} -- type QSOON or QSOOFF)")

    def stop(self) -> None:
        self._stop_flag.set()


class GpioSquelchSource(SquelchSource):
    def __init__(self, chip: str, line: int, debounce_ms: float = 20.0) -> None:
        super().__init__()
        self.chip_path = chip
        self.line_offset = line
        self.debounce_s = debounce_ms / 1000.0
        self.is_open = False
        self._request = None
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

    def start(self) -> None:
        import gpiod
        from gpiod.line import Bias, Direction, Edge

        self._request = gpiod.request_lines(
            self.chip_path,
            consumer="voxdole-squelch",
            config={
                self.line_offset: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    bias=Bias.PULL_UP,
                    edge_detection=Edge.BOTH,
                )
            },
        )
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        last_change = 0.0
        while not self._stop_flag.is_set():
            if not self._request.wait_edge_events(timeout=0.5):
                continue
            for event in self._request.read_edge_events():
                now = time.monotonic()
                if now - last_change < self.debounce_s:
                    continue
                last_change = now
                pressed = event.event_type.name == "FALLING_EDGE"
                self.is_open = pressed
                self._fire(pressed)

    def stop(self) -> None:
        self._stop_flag.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._request:
            self._request.release()


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--keyboard", action="store_true", help="use KeyboardSquelchSource for a standalone test")
    p.add_argument("--gpio", nargs=2, metavar=("CHIP", "LINE"), help="use GpioSquelchSource for a standalone test")
    args = p.parse_args()

    if args.gpio:
        chip, line = args.gpio
        source = GpioSquelchSource(chip=chip, line=int(line))
    elif args.keyboard:
        source = KeyboardSquelchSource()
    else:
        p.print_help()
        return

    source.on_change(lambda is_open: print(f"  [callback fired] is_open={is_open}"))
    source.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        source.stop()
        print("\nstopped.")


if __name__ == "__main__":
    main()
