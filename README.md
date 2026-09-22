# VoxDole

VoxDole is an automated voicemail system for the [Glutte VHF relay on the Massif de la Dole](https://github.com/Glutte).
built as part of my Bachelor thesis at HEIG-VD.

When someone can't reach the person they're
calling over the relay, they can leave them a voice message instead, and the recipient can
call back later to hear it. All through using the relay as you would normally, but voicemails can also be seen through the simple web application.

This project was built with the [Luna SL1680](https://labs.toradex.com/projects/luna-sl1680) board in mind so the code can be specific (eg. GPIO pins integration)

## Project layout

The code is split into two parts. 


`onboard/` is everything that goes on the board:
it's a self-contained Docker build, so it can be copied over and built there directly.


`outboard/` is tooling for development and pre-deployment. Such as generating the audio clips for the app with the text-to-speech.

## Getting set up (on your computer)

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r outboard/requirements.txt
```

### Getting the TTS voice model + audio clips

Download it yourself and place it in `outboard/models/piper/`:

```bash
mkdir -p outboard/models/piper
curl -L -o outboard/models/piper/fr_FR-siwis-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx
curl -L -o outboard/models/piper/fr_FR-siwis-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json
```
_note: other piper models can be used here if you do not like siwis_

Then generate the voice clips:

```bash
cd outboard
python generate_tts.py
```

This reads through `tts_manifest.txt` and writes one `.wav` file per line into
`onboard/assets/tts/`. You are free to change the sentences in the manifest.

## Deploying to the board

```bash
scp -r onboard torizon@<BOARD_IP>:~/voxdole
ssh torizon@<BOARD_IP>
cd ~/voxdole
docker compose build
```

### Configuration

Before starting the app, two things in `docker-compose.yml`'s `command:` need to be set for
your actual hardware: audio devices, and where the relay's signals come from.

#### Audio devices

```bash
docker run --rm -it --device /dev/snd voxdole:latest --list-devices
```
Find your mic and speaker in the list, then set them:
```yaml
command: ["--input-device-name", "YOUR_MIC", "--output-device-name", "YOUR_SPEAKER", ...]
```
Device indices shift around across reboots, which is why `--input-device-name` and
`--output-device-name` match by a substring of the device's name instead of a fixed index.

_Note : as I2S input/output are not handled **yet** you will need to know which device you want your input/outputs_

#### Relay signal

Two options for `--relay-signal`:

**Keyboard** (default, no hardware needed):
```yaml
command: [..., "--relay-signal", "keyboard"]
```
Then type `QSOON`/`QSOOFF`/`OPEN1`/`OISIF` in the attached terminal to simulate the relay. 

**Real GPIO pins**, once wired up:
```yaml
command: [..., "--relay-signal", "gpio",
          "--relay-qso-chip", "/dev/gpiochipN", "--relay-qso-line", "N",
          "--relay-wake-chip", "/dev/gpiochipN", "--relay-wake-line", "N"]
```
TODO : add the schema of the wired up board with the pins and the corresponding chip and offset for the board

### Running it

```bash
docker compose up -d --build
```

`docker-compose.yml` runs two containers: `voxdole-app` (the voicemail) and `voxdole-web` (the web archive, on port 8080).
