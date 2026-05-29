# syntax=docker/dockerfile:1
# One-shot Bible ingestion job. CPU-only (works on the Mac dev host); the
# embedding model is baked in at build time so ingestion needs no network.
FROM python:3.12-slim AS runtime

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# CPU-only torch keeps the image small and avoids pulling CUDA wheels.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-cache the embedding model (defaults match .env.example; override at build).
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL}
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY ingest.py .
COPY data ./data

CMD ["python", "ingest.py"]
