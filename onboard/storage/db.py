from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "voxdole.db"

# TODO : maybe log when delivered ? just mmore info
SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    sender_callsign TEXT NOT NULL,
    recipient_callsign TEXT NOT NULL,
    audio_path TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0
);
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def add_message(conn: sqlite3.Connection, sender_callsign: str, recipient_callsign: str, audio_path: str) -> int:
    recorded_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO messages (sender_callsign, recipient_callsign, audio_path, recorded_at) "
        "VALUES (?, ?, ?, ?)",
        (sender_callsign, recipient_callsign, audio_path, recorded_at),
    )
    conn.commit()
    return cur.lastrowid


def get_pending_messages(conn: sqlite3.Connection, recipient_callsign: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM messages WHERE recipient_callsign = ? AND delivered = 0 "
        "ORDER BY recorded_at ASC",
        (recipient_callsign,),
    )
    return cur.fetchall()


def mark_delivered(conn: sqlite3.Connection, message_id: int) -> None:
    conn.execute("UPDATE messages SET delivered = 1 WHERE id = ?", (message_id,))
    conn.commit()


def get_all_messages(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM messages ORDER BY recorded_at DESC")
    return cur.fetchall()


def get_message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    return cur.fetchone()

# TODO : can be removed ?
def _self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        conn = connect(db_path)
        msg_id = add_message(conn, "HB9EGM", "HB9ICJ", "messages/1.wav")
        conn.close()
        print(f"inserted message {msg_id}, closed connection")

        conn = connect(db_path)  # fresh connection, same file
        pending = get_pending_messages(conn, "HB9ICJ")
        assert len(pending) == 1, f"expected 1 pending message after reopen, got {len(pending)}"
        assert pending[0]["sender_callsign"] == "HB9EGM"
        assert pending[0]["delivered"] == 0
        print(f"reopened db, found pending message: {dict(pending[0])}")

        mark_delivered(conn, pending[0]["id"])
        pending_after = get_pending_messages(conn, "HB9ICJ")
        assert len(pending_after) == 0, "message should no longer be pending after mark_delivered"
        conn.close()
        print("marked delivered, confirmed no longer pending -- self-test passed")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        _self_test()
    else:
        p.print_help()
