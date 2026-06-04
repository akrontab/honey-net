FROM python:3.9-slim-bullseye
RUN pip install --no-cache-dir heralding==1.0.7
# /data is the working directory; heralding generates TLS certs here on first run.
# Cert files are ephemeral (not a mounted volume) — regenerated on each restart.
WORKDIR /data
CMD ["heralding", "-c", "/etc/heralding/heralding.yml"]
