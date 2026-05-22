FROM python:3.12-slim

# System deps + Chromium for stealth scrapers (Naukri/PH fallback paths).
# chromium-driver is the matching driver; undetected-chromedriver will use
# the system one when available, otherwise auto-downloads. The fonts/libs
# below are the standard "headless Chrome in Debian" set — without them
# Chromium crashes on launch with cryptic libnss / libfontconfig errors.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
      curl \
      chromium \
      chromium-driver \
      fonts-liberation \
      libasound2 \
      libatk-bridge2.0-0 \
      libatk1.0-0 \
      libcups2 \
      libdrm2 \
      libgbm1 \
      libgtk-3-0 \
      libnspr4 \
      libnss3 \
      libx11-xcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxfixes3 \
      libxrandr2 \
      xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Point undetected-chromedriver at the system chromium binary so it doesn't
# try to launch a missing /opt/google/chrome/chrome.
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_PATH=/usr/bin/chromium \
    STEALTH_USER_DATA_DIR=/tmp/chrome_profile

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
