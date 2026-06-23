# EchoAssist backend API (Sprint 6). Build context = backend/.
#
# Two modes, selected by the PIP_EXTRAS build arg:
#   * light (default) — data/API + RAG ingest + WebSocket + Gemini LLM client. No local
#     STT/TTS models, so POST /calls returns 503 (use the host or the voice image for calls).
#       docker compose up -d --build api
#   * voice (full) — adds faster-whisper + Kokoro so replay calls run in-container (large).
#       docker compose --profile voice up -d --build api-voice
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg: used by the telephonize / transcription tooling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Light by default; the voice image overrides this with "all".
ARG PIP_EXTRAS="api,observability,storage,state,rag,llm-gemini"

# The editable install reads config*/src* from [tool.setuptools.packages.find],
# so the source tree must be present before installing.
COPY . .
RUN pip install -e ".[${PIP_EXTRAS}]"

# Bake a seed of the demo docs so a (mounted, empty) docs volume can be populated on
# first start without masking the bundled set — see scripts/docker-entrypoint.sh.
RUN cp -r data/docs data/docs.seed

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

ENTRYPOINT ["sh", "/app/scripts/docker-entrypoint.sh"]
CMD ["python", "scripts/serve.py"]
