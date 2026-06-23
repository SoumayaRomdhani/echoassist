# EchoAssist backend API (Sprint 6). Build context = backend/.
#   docker compose up -d --build api
#
# Installs the extras needed to serve the API, persist data, run RAG ingest, and
# use the Gemini LLM client. The local STT/TTS models (faster-whisper, Kokoro)
# are large and GPU/CPU heavy — add the "all" extra if you want live in-container
# calls; the data-serving API, RAG, and WebSocket do not need them.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg: used by the telephonize / transcription tooling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The editable install reads config*/src* from [tool.setuptools.packages.find],
# so the source tree must be present before installing.
COPY . .
RUN pip install -e ".[api,observability,storage,state,rag,llm-gemini]"

EXPOSE 8000

# Healthcheck hits the liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["python", "scripts/serve.py"]
