FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv espeak-ng ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 TZ=Europe/Paris
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && npm install -g @google/gemini-cli@0.61.0
COPY pipelineia pipelineia
COPY prompts prompts
COPY config.yaml .
RUN mkdir -p /app/data /app/output /app/logs && chown -R node:node /app
USER node
CMD ["python", "-m", "pipelineia", "run"]
