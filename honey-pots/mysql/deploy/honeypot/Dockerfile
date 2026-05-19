FROM python:3.12-slim
WORKDIR /app
COPY server.py .
RUN mkdir -p /logs
CMD ["python", "-u", "server.py"]
