FROM torizon/debian:4

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    libportaudio2 \
    libsndfile1 \
    alsa-utils \
    libatomic1 \
    libgomp1 \
    libgpiod-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

ENTRYPOINT ["python3", "main.py"]
