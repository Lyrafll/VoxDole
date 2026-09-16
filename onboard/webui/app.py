"""Read-only web dashboard for recorded messages.

Runs as its own process alongside main.py, reading the same SQLite DB --
never writes to it, so it's safe to run (or restart) independently of the
répondeur itself.

Usage (from the onboard/ directory, same cwd convention as main.py):
    python3 -m webui.app [--host 0.0.0.0] [--port 8080]
"""
from __future__ import annotations

import argparse

from flask import Flask, jsonify, render_template, send_file

import config
from storage.db import connect, get_all_messages, get_message


def create_app() -> Flask:
    app = Flask(__name__)
    db = connect(config.DB_PATH)

    @app.get("/")
    def index():
        return render_template("messages.html")

    @app.get("/api/messages")
    def api_messages():
        return jsonify([dict(row) for row in get_all_messages(db)])

    @app.get("/audio/<int:message_id>")
    def audio(message_id: int):
        row = get_message(db, message_id)
        if row is None:
            return "not found", 404
        return send_file(row["audio_path"], mimetype="audio/wav")

    return app


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()

    create_app().run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
