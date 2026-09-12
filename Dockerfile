# Multi-arch base: pulling this FROM line on a Raspberry Pi (arm64/armv7)
# and running `docker build` there produces a native Pi image with no
# cross-compilation setup needed.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt .
# gcc/libffi-dev cover the rare case a dependency has no prebuilt wheel for
# your Pi's architecture and pip needs to compile it from source.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc libffi-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY memefly/ memefly/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

RUN useradd --create-home --uid 1000 memefly \
    && mkdir -p /app/data \
    && chown -R memefly:memefly /app
USER memefly

# Runtime data (connectome cache, state.json, activity_log.csv, trade_log.csv)
# lives here so it can be shared via a volume between the bot and dashboard
# containers and survives image rebuilds.
WORKDIR /app/data
VOLUME ["/app/data"]

EXPOSE 8765

CMD ["/app/entrypoint.sh"]
