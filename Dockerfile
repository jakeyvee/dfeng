# =============================================================================
# Dongfeng Experience Community bot — production image (VOL-213)
# =============================================================================
# Single long-poll Python bot. Slim base, deps installed from requirements.txt,
# runs as a non-root user, entrypoint `python -m dfeng_bot.main`.
#
# Secrets are NEVER baked in. Provide them at runtime via env_file / secret
# mounts (see docker-compose.yml and docs/production-deployment.md). The Google
# service-account JSON is a read-only mounted secret, not a build arg.
# -----------------------------------------------------------------------------
FROM python:3.12-slim

# - PYTHONDONTWRITEBYTECODE: no .pyc clutter in the image layer.
# - PYTHONUNBUFFERED: flush stdout/stderr immediately so `docker logs` is live
#   (the bot's structured logs go to stdout/stderr — see docs).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (better layer caching). requirements.txt is the
# canonical runtime dependency list.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source. The package lives under src/ (src layout); adding
# src to PYTHONPATH lets `python -m dfeng_bot.main` import it without a build step.
COPY src ./src
ENV PYTHONPATH=/app/src

# Run as a non-root user.
RUN useradd --create-home --uid 10001 dfeng \
    && chown -R dfeng:dfeng /app
USER dfeng

# Long-poll bot: no port to expose by default. (For webhook mode, publish
# DFENG_WEBHOOK_PORT in docker-compose and set DFENG_RUN_MODE=webhook.)
ENTRYPOINT ["python", "-m", "dfeng_bot.main"]
