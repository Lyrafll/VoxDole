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

# Mappings Constant to wav file
PHRASE_ASK_CALLER = "ask_caller_callsign"
PHRASE_MESSAGE_RECORDED = "message_recorded"
PHRASE_MESSAGE_FROM_PREFIX = "message_from_prefix"
PHRASE_END_OF_MESSAGES = "end_of_messages"

PHRASE_CALLER_ACK_PREFIX = "caller_ack_prefix"
PHRASE_ASK_RECEIVER_SUFFIX = "ask_receiver_suffix"
PHRASE_RECEIVER_ACK_PREFIX = "receiver_ack_prefix"
PHRASE_ASK_RECORD_SUFFIX = "ask_record_suffix"
PHRASE_MESSAGES_FOR_PREFIX = "messages_for_prefix"
PHRASE_NO_MESSAGES_FOR_PREFIX = "no_messages_for_prefix"
