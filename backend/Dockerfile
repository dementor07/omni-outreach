FROM python:3.12-slim

# System deps
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Deps layer (cached unless requirements change)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY backend/alembic.ini .
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY scripts ./scripts

RUN chown -R app:app /app
USER app

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
