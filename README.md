# VoxDole

VoxDole is an automated voicemail system for the Glutte VHF relay on the Massif de la Dole,
built as part of my Bachelor thesis at HEIG-VD. When someone can't reach the person they're
calling over the relay, they can leave them a voice message instead, and the recipient can
call back later to hear it. The full design is written up in `ARCHITECTURE.md`, one level up
in the `TB` project folder.

## Project layout

The code is split into two parts. `onboard/` is everything that actually runs on the board:
it's a self-contained Docker build, so it can be copied over and built there directly.
`outboard/` is tooling I only use on my own machine during development, mainly for generating
the voice prompts, and none of it ever gets deployed.

## Getting set up

```bash
python -m venv .venv
.venv/Scripts/activate   # source .venv/bin/activate on Linux
pip install -r outboard/requirements.txt -r onboard/requirements.txt
```

### Getting the TTS voice model

I didn't commit this to the repo since it's a 61MB binary file and didn't seem worth the repo
size. Download it yourself and place it in `outboard/models/piper/`:

```bash
mkdir -p outboard/models/piper
curl -L -o outboard/models/piper/fr_FR-siwis-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx
curl -L -o outboard/models/piper/fr_FR-siwis-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json
```

Then generate the voice clips:

```bash
cd outboard
python generate_tts.py
```

This reads through `tts_manifest.txt` and writes one `.wav` file per line into
`onboard/assets/tts/`.

## Running it locally

```bash
cd onboard
python main.py --list-devices
python main.py --device N --output-device M
```

Since I don't have real relay hardware on my desk, I simulate the relay's signals by typing in
the terminal: `QSOON`/`QSOOFF` for squelch, and `OPEN1`/`OISIF` for the relay waking up and
going back to sleep. The app only does anything between an `OPEN1` and the next `OISIF` (or a
timeout standing in for a missed one) -- meant to mirror how the real relay would only be
active while it's actually open.

Device indices shift around across reboots, so `--input-device-name` and `--output-device-name`
match a device by a substring of its name instead, e.g. `--output-device-name PRO`.

## Deploying to the board

```bash
scp -r onboard torizon@<BOARD_IP>:~/voxdole
ssh torizon@<BOARD_IP>
cd ~/voxdole
docker compose up -d --build
```

`docker-compose.yml` runs two containers: `app` (the répondeur itself) and `web` (the message
archive, on port 8080). `VOXDOLE_DATA_DIR` is what tells the app where to store `voxdole.db`
and the recorded messages -- both containers mount the same host folder there, so messages
survive a rebuild.

On the real board, `--relay-signal gpio` reads the QSO/wake/sleep signals from actual GPIO pins
instead of the keyboard, each one its own `--relay-*-chip`/`--relay-*-line` pair (wake and
sleep are optional -- without them the app just never hears those signals). Which
`/dev/gpiochipN` and line number a given header pin actually maps to isn't documented anywhere
for this board -- I had to find it empirically with `gpiomon`, pressing the pin and watching
which line reacted.
