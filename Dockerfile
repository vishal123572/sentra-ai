FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements-ml.txt
RUN mkdir -p /data && chown -R 10001:10001 /app /data
USER 10001:10001
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=3)"
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8080", "--database", "/data/satsa.sqlite3"]
