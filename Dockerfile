FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 blue

# The build context excludes local credentials and frontend-only assets.
COPY --chown=blue:blue run.py ./
COPY --chown=blue:blue ai_data ./ai_data
USER blue
EXPOSE 8000
CMD ["python", "run.py", "api"]
