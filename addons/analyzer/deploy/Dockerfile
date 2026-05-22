FROM python:3.12-slim
RUN pip install --no-cache-dir requests
WORKDIR /app
COPY analyzer.py .
CMD ["python", "-u", "analyzer.py"]
