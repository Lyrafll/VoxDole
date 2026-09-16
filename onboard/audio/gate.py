"""Squelch/QSO-open signal source -- tells the pipeline when a transmission
starts and ends. Confirmed with Matthias: Glutte's relay exposes this as a
GPIO *level*, active for the whole QSO (not two separate edge pulses).
GpioSquelchSource will read it directly once the pin is wired up. Until
then, KeyboardSquelchSource drives the same event from typed commands --
same interface, swap the source later.

Usage:
    python -m audio.gate --keyboard              # type QSOON / QSOOFF
    python -m audio.gate --gpio /dev/gpiochip0 17 # press the real button
"""
from __future__ import annotations

import abc
import threading
import time
from typing import Callable

SquelchCallback = Callable[[bool], None]  # called with True on open, False on close


class SquelchSource(abc.ABC):
    """Abstract trigger for "a transmission just started/ended"."""

    def __init__(self) -> None:
        self._callbacks: list[SquelchCallback] = []

    def on_change(self, callback: SquelchCallback) -> None:
        self._callbacks.append(callback)

    def _fire(self, is_open: bool) -> None:
        for cb in self._callbacks:
            cb(is_open)

    @abc.abstractmethod
    def start(self) -> None:
        """Start listening for events (non-blocking -- spawns its own thread)."""

    @abc.abstractmethod
    def stop(self) -> None:
        ...


class KeyboardSquelchSource(SquelchSource):
    """Dev/testing source: type QSOON / QSOOFF (case-insensitive) to
    simulate the real GPIO level signal. Not a toggle -- matches the real
    signal's shape (active for the whole QSO).
    """

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
    """Real hardware source: a physical button wired to a GPIO line,
    standing in for the relay's real squelch signal until that's wired up
    for real (see GPIO_BUTTON_PLAN.md for the wiring/pin reasoning).

    Active-low, matching the header's default internal pull-up: released
    reads HIGH, pressed shorts the line to GND and reads LOW. `chip`/`line`
    must come from actually running `gpioinfo`/`gpiomon` against the wired
    button, not guessed from the datasheet's pin naming -- the kernel's
    line names don't always match the board's silkscreen labels.

    NOTE: written against the libgpiod v2 Python API (`gpiod` package) from
    its documented behavior -- not verified against the board's actual
    installed package, since that wasn't available to test from here. If
    the exact method/class names below don't match what's installed,
    smoke-test with `python -m audio.gate --gpio /dev/gpiochipN LINE`
    first (fast, seconds per attempt) before wiring it into the full app --
    much cheaper to debug there than through a full Docker rebuild.
    """

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
        import gpiod  # noqa: F401 -- only for the Type enum used below

        last_change = 0.0
        while not self._stop_flag.is_set():
            if not self._request.wait_edge_events(timeout=0.5):
                continue
            for event in self._request.read_edge_events():
                now = time.monotonic()
                if now - last_change < self.debounce_s:
                    continue
                last_change = now
                # falling edge (HIGH->LOW) = button pressed = QSO opens
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

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keyboard", action="store_true", help="use KeyboardSquelchSource for a standalone test")
    p.add_argument("--gpio", nargs=2, metavar=("CHIP", "LINE"),
                    help="use GpioSquelchSource for a standalone test, e.g. --gpio /dev/gpiochip0 17 "
                         "-- fast way to confirm the button/chip/line actually work before wiring "
                         "GpioSquelchSource into main.py")
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
