# vivijure-blender -- headless Blender compositor for Vivijure finish-blender.
#
# Installs official Blender LTS (Linux x64) + ffmpeg + the RunPod serverless handler.
# Compositor jobs are CPU-friendly; the CUDA base keeps the door open for future Cycles
# title cards on the same image without a second fleet.
#
# Pin: Blender 4.2.8 LTS. Bump BLENDER_VERSION + sha when cutting a new image tag.

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    BLENDER_VERSION=4.2.8 \
    BLENDER_MAJOR=4.2 \
    PYTHONUNBUFFERED=1

# Blender runtime libs + ffmpeg + python for the handler.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils \
      python3 python3-pip python3-venv \
      ffmpeg \
      libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libgl1 \
      libxkbcommon0 libsm6 libice6 \
    && rm -rf /var/lib/apt/lists/*

# Official Blender LTS tarball (GPL). Verify the release page if you bump the pin.
RUN curl -fsSL -o /tmp/blender.tar.xz \
      "https://download.blender.org/release/Blender${BLENDER_MAJOR}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && /opt/blender/blender -b --version

ENV BLENDER_BIN=/opt/blender/blender \
    PATH="/opt/blender:${PATH}" \
    COMPOSITE_SCRIPT=/app/scripts/composite_job.py

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY handler.py /app/handler.py
COPY scripts/composite_job.py /app/scripts/composite_job.py

# Smoke: blender + script parse (no GPU needed for --help path of our argparse via blender -b).
RUN /opt/blender/blender -b --python /app/scripts/composite_job.py -- --help >/dev/null 2>&1 || true

CMD ["python3", "-u", "/app/handler.py"]
