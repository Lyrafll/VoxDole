# VoxDole

Automated voicemail (répondeur) for the Glutte VHF relay. HEIG-VD Bachelor
Thesis project. See `ARCHITECTURE.md` (currently at the repo root of the
`TB` project, one level up) for the full design.

## Structure

- `onboard/` — everything that runs on the board. Self-contained: this is
  the Docker build root.
- `outboard/` — dev-only tooling that never ships (TTS clip generation).

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate   # or source .venv/bin/activate on Linux
pip install -r outboard/requirements.txt -r onboard/requirements.txt
```

### TTS voice model (dev-only, for generating clips)

Not committed to the repo (61MB binary, not worth the repo bloat).
Download it and place it at `outboard/models/piper/`:

```bash
mkdir -p outboard/models/piper
curl -L -o outboard/models/piper/fr_FR-siwis-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx
curl -L -o outboard/models/piper/fr_FR-siwis-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json
```

Then generate the TTS clips:

```bash
cd outboard
python generate_tts.py
```

Writes one `.wav` per `tts_manifest.txt` line into `onboard/assets/tts/`.

## Running locally

```bash
cd onboard
python main.py --list-devices
python main.py --device N --output-device M
```

Type `QSOON` / `QSOOFF` to simulate the relay's squelch signal.

## Deploying to the board

```bash
scp -r onboard torizon@<BOARD_IP>:~/voxdole
ssh torizon@<BOARD_IP>
cd ~/voxdole
mkdir -p ~/voxdole-data
docker build -t voxdole .
docker run --rm -it --device /dev/snd -v ~/voxdole-data:/data -e VOXDOLE_DATA_DIR=/data voxdole
```

`VOXDOLE_DATA_DIR` controls where `voxdole.db` and recorded messages live
-- without the volume mount, `docker run --rm` deletes them on exit.
