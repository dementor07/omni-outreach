# Camoufox headless-browser microservice.
#
# Isolates the Playwright/Camoufox (anti-detect browser) dependency in its own
# container so the Rust muscle and Python backend stay slim. The muscle calls
# this service over the internal Docker network to scrape job boards with bot
# protection (Naukri) and to render JS-heavy company team pages.
#
# Ported from omniagenticai/omni-outreach feature/dev-automation
# (services/camoufox) and hardened: shared-secret auth, env config, team crawl.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-fetch the Camoufox browser binary into the image so first request is fast.
RUN python -m camoufox fetch

COPY . .

EXPOSE 8100

# Probe the ACTIVE deep check: it self-heals a dead browser in-process and only
# fails (503) when the browser is genuinely unrecoverable, so a transient flake
# never trips a restart but a wedged service does. Generous timeout: a heal
# relaunches the browser (a few seconds). start-period covers first-boot launch.
HEALTHCHECK --interval=30s --timeout=20s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8100/health/deep', timeout=18)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100", "--log-level", "info"]
