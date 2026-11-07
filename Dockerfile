FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 rackdisplay
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

COPY deploy/config.docker.toml /etc/rackdisplay/config.toml
USER rackdisplay
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]

ENTRYPOINT ["rackdisplay"]
# With nothing mounted the container shows made-up data: `docker run -p 8080:8080 rackdisplay`.
CMD ["serve", "--demo", "-c", "/etc/rackdisplay/config.toml"]
