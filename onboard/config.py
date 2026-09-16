import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("VOXDOLE_DATA_DIR", ROOT))

VOSK_MODEL_PATH = ROOT / "models" / "vosk" / "vosk-model-small-fr-0.22-glutte"
ASSETS_TTS_DIR = ROOT / "assets" / "tts"
MESSAGES_DIR = DATA_DIR / "messages"
DB_PATH = DATA_DIR / "voxdole.db"

SAMPLE_RATE = 16000
MIN_CONFIDENCE = 0.9
REPLY_TIMEOUT_SECONDS = 25.0

PHRASE_ASK_CALLER = "ask_caller_callsign"
PHRASE_CONFIRM_PREFIX = "confirm_prefix"
PHRASE_CONFIRM_SUFFIX = "confirm_suffix"
PHRASE_RETRY_CALLER = "retry_caller_callsign"
PHRASE_ASK_RECEIVER = "ask_receiver"
PHRASE_RECEIVER_CONFIRM_PREFIX = "receiver_confirm_prefix"
PHRASE_RETRY_RECEIVER = "retry_receiver_callsign"
PHRASE_ASK_RECORD = "ask_record"
PHRASE_MESSAGE_RECORDED = "message_recorded"
PHRASE_NO_MESSAGES = "no_messages"
PHRASE_MESSAGE_FROM_PREFIX = "message_from_prefix"
PHRASE_END_OF_MESSAGES = "end_of_messages"
PHRASE_CANCELLED = "cancelled"
