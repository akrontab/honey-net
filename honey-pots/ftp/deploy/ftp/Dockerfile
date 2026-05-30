FROM python:3.12-slim

RUN pip install --no-cache-dir pyftpdlib

WORKDIR /app
COPY ftp_honeypot.py .

EXPOSE 21

CMD ["python", "ftp_honeypot.py"]
