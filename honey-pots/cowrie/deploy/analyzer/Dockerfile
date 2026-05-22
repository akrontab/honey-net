FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends yara inotify-tools file jq curl \
    && rm -rf /var/lib/apt/lists/*
COPY analyze.sh /analyze.sh
RUN chmod +x /analyze.sh
ENTRYPOINT ["/analyze.sh"]
