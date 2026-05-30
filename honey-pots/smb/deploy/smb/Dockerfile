FROM python:3.12-slim

RUN pip install --no-cache-dir impacket

WORKDIR /app
COPY smb_honeypot.py .

EXPOSE 139 445

CMD ["python", "smb_honeypot.py"]
