FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 blue

# Deliberately copy only runtime files: no .env, Git history, frontend or local media.
COPY --chown=blue:blue run.py ./
COPY --chown=blue:blue ai_data ./ai_data
USER blue
EXPOSE 8000
CMD ["python", "run.py", "api"]
