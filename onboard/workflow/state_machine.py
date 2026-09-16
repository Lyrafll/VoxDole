from __future__ import annotations

import threading
import time
from enum import Enum, auto
from typing import Callable

import numpy as np

import config
from scoring import extract_callsigns
from tts.compose import compose, concat, load_clip

Reply = Callable[[np.ndarray, int], None]
SaveMessage = Callable[[str, str, bytes], None]
FetchMessages = Callable[[str], list[tuple[str, np.ndarray]]]
StateChange = Callable[["State"], None]
TimeoutHandler = Callable[["State"], None]


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    GLUTTE_HEARD = auto()
    CALLER_ID_ASK = auto()
    CALLER_ID_CONFIRM = auto()
    RECEIVER_ID_ASK = auto()
    RECEIVER_ID_CONFIRM = auto()
    RECORDING = auto()
    ANNOUNCING = auto()

WAITING_STATES = {
    State.CALLER_ID_ASK, State.CALLER_ID_CONFIRM,
    State.RECEIVER_ID_ASK, State.RECEIVER_ID_CONFIRM,
    State.RECORDING,
}

CANCELABLE_STATES = WAITING_STATES


def _strip_confidence(words: list[str]) -> list[str]:
    """Vosk marks a below-threshold word as "[word]" (see result_text() in
    stt/engine.py). Strip that for keyword matching (glutte/intent/confirm/
    cancel) so a merely-uncertain recognition of a closed-vocabulary word
    still counts -- extract_callsigns() still gets the original bracketed
    words, since it deliberately treats a bracket as an uncertain-token
    marker that breaks a callsign run.
    """
    return [w[1:-1] if w.startswith("[") and w.endswith("]") else w for w in words]


class Workflow:
    def __init__(self, reply: Reply, save_message: SaveMessage, fetch_messages: FetchMessages,
                 timeout_seconds: float = config.REPLY_TIMEOUT_SECONDS,
                 on_state_change: StateChange | None = None,
                 on_timeout: TimeoutHandler | None = None):
        self.reply = reply
        self.save_message = save_message
        self.fetch_messages = fetch_messages
        self.timeout_seconds = timeout_seconds
        self.on_state_change = on_state_change
        self.on_timeout = on_timeout

        self.state = State.IDLE
        self.purpose: str | None = None  # "leave" | "listen"
        self.caller_callsign: str | None = None
        self.receiver_callsign: str | None = None

        self._words: list[str] = []
        self._first_word_seen = False
        self._cancel_checked_this_qso = False
        self._cancel_armed = False
        self._pending_reply: str | tuple[str, str] | None = None
        self._deadline: float | None = None
        self._recording_this_qso = False
        self._message_audio: list[bytes] = []
        self._lock = threading.Lock()

    def _set_state(self, state: State) -> None:
        self.state = state
        if self.on_state_change:
            self.on_state_change(state)

    def on_squelch(self, is_open: bool) -> None:
        with self._lock:
            if is_open:
                self._on_qso_start()
            else:
                self._on_qso_end()

    def _on_qso_start(self) -> None:
        if self.state == State.IDLE:
            self._set_state(State.LISTENING)
        self._words = []
        self._first_word_seen = False
        self._cancel_checked_this_qso = False
        self._cancel_armed = False
        self._deadline = None
        self._recording_this_qso = self.state == State.RECORDING

    def _on_qso_end(self) -> None:
        if self._recording_this_qso:
            self._finish_recording()
            return

        if self._pending_reply is not None:
            self._play(self._pending_reply)
            self._pending_reply = None

        if self.state == State.ANNOUNCING:
            self._reset()
        elif self.state in (State.LISTENING, State.GLUTTE_HEARD):
            self._set_state(State.IDLE)
        elif self.state in WAITING_STATES:
            self._deadline = time.monotonic() + self.timeout_seconds

    def on_final_result(self, text: str) -> None:
        words = text.split()
        if not words:
            return

        clean_words = _strip_confidence(words)

        with self._lock:
            if self.state in CANCELABLE_STATES and self._check_cancel(clean_words):
                return

            # a single result can carry the whole trigger phrase ("glutte
            # laisser un message" in one breath) -- check intent on the same
            # words right after glutte transitions us into GLUTTE_HEARD.
            # Deliberately NOT a general cascade across every state: letting
            # ASK<->CONFIRM re-dispatch the same words caused a real
            # infinite loop (a stray "non" in mid-callsign hesitation text
            # got reinterpreted as a confirm answer, bouncing forever).
            if self.state == State.LISTENING:
                self._check_glutte(clean_words)

            # extract_callsigns() wants the ORIGINAL (bracketed) words -- a
            # low-confidence letter should still break a callsign run. Every
            # other check wants clean_words -- see _strip_confidence().
            match self.state:
                case State.GLUTTE_HEARD:
                    self._check_intent(clean_words)
                case State.CALLER_ID_ASK:
                    self._check_callsign(words, "caller")
                case State.CALLER_ID_CONFIRM:
                    self._check_confirm(clean_words, "caller")
                case State.RECEIVER_ID_ASK:
                    self._check_callsign(words, "receiver")
                case State.RECEIVER_ID_CONFIRM:
                    self._check_confirm(clean_words, "receiver")

    def on_audio_frame(self, frame: bytes) -> None:
        with self._lock:
            if self._recording_this_qso:
                self._message_audio.append(frame)

    def tick(self) -> None:
        with self._lock:
            if self._deadline is not None and time.monotonic() > self._deadline:
                if self.on_timeout:
                    self.on_timeout(self.state)
                self._reset()

    def _check_cancel(self, words: list[str]) -> bool:
        if not self._cancel_checked_this_qso:
            self._cancel_checked_this_qso = True
            self._cancel_armed = words[0] == "glutte"
        if self._cancel_armed and "annule" in words:
            self._reset()
            self._pending_reply = config.PHRASE_CANCELLED
            return True
        return False

    def _check_glutte(self, words: list[str]) -> None:
        if self._first_word_seen:
            return
        self._first_word_seen = True
        if words[0] == "glutte":
            self._set_state(State.GLUTTE_HEARD)

    def _check_intent(self, words: list[str]) -> None:
        self._words.extend(words)
        has_message = "message" in self._words
        if "laisser" in self._words and has_message:
            self.purpose = "leave"
        elif "écouter" in self._words and has_message:
            self.purpose = "listen"
        else:
            return
        self._set_state(State.CALLER_ID_ASK)
        self._pending_reply = config.PHRASE_ASK_CALLER
        self._words = []

    def _check_callsign(self, words: list[str], target: str) -> None:
        self._words.extend(words)
        callsigns = extract_callsigns(" ".join(self._words))
        if not callsigns:
            return
        callsign = callsigns[-1]
        self._words = []
        if target == "caller":
            self.caller_callsign = callsign
            self._set_state(State.CALLER_ID_CONFIRM)
            self._pending_reply = ("confirm_caller", callsign)
        else:
            self.receiver_callsign = callsign
            self._set_state(State.RECEIVER_ID_CONFIRM)
            self._pending_reply = ("confirm_receiver", callsign)

    def _check_confirm(self, words: list[str], target: str) -> None:
        if "oui" in words:
            if target == "caller":
                if self.purpose == "listen":
                    self._set_state(State.ANNOUNCING)
                    self._pending_reply = ("announce", self.caller_callsign)
                else:
                    self._set_state(State.RECEIVER_ID_ASK)
                    self._pending_reply = config.PHRASE_ASK_RECEIVER
            else:
                self._set_state(State.RECORDING)
                self._pending_reply = config.PHRASE_ASK_RECORD
        elif "non" in words:
            if target == "caller":
                self._set_state(State.CALLER_ID_ASK)
                self._pending_reply = config.PHRASE_RETRY_CALLER
            else:
                self._set_state(State.RECEIVER_ID_ASK)
                self._pending_reply = config.PHRASE_RETRY_RECEIVER
        else:
            return
        self._words = []

    def _finish_recording(self) -> None:
        audio = b"".join(self._message_audio)
        self._message_audio = []
        self._recording_this_qso = False
        self.save_message(self.caller_callsign, self.receiver_callsign, audio)
        self._play(config.PHRASE_MESSAGE_RECORDED)
        self._reset()

    def _play(self, pending: str | tuple[str, str]) -> None:
        if isinstance(pending, str):
            audio, sr = load_clip(pending)
            self.reply(audio, sr)
            return

        kind, callsign = pending
        if kind == "announce":
            self._play_announcement(callsign)
            return

        prefix = config.PHRASE_CONFIRM_PREFIX if kind == "confirm_caller" else config.PHRASE_RECEIVER_CONFIRM_PREFIX
        audio, sr = concat(load_clip(prefix), compose(callsign), load_clip(config.PHRASE_CONFIRM_SUFFIX))
        self.reply(audio, sr)

    def _play_announcement(self, callsign: str) -> None:
        messages = self.fetch_messages(callsign)
        if not messages:
            audio, sr = load_clip(config.PHRASE_NO_MESSAGES)
            self.reply(audio, sr)
            return

        for sender, audio in messages:
            intro, sr = concat(load_clip(config.PHRASE_MESSAGE_FROM_PREFIX), compose(sender))
            self.reply(intro, sr)
            self.reply(audio, config.SAMPLE_RATE)

        audio, sr = load_clip(config.PHRASE_END_OF_MESSAGES)
        self.reply(audio, sr)

    def _reset(self) -> None:
        self._set_state(State.IDLE)
        self.purpose = None
        self.caller_callsign = None
        self.receiver_callsign = None
        self._words = []
        self._first_word_seen = False
        self._cancel_checked_this_qso = False
        self._cancel_armed = False
        self._pending_reply = None
        self._deadline = None
        self._recording_this_qso = False
        self._message_audio = []
