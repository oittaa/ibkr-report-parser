FROM python:3.14.6-slim AS base

ARG DEBIAN_FRONTEND=noninteractive

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED=True
ENV APP_HOME=/app
ENV GUNICORN_WORKERS=1
ENV GUNICORN_THREADS=8
ENV PORT=8080

WORKDIR $APP_HOME
COPY main.py pyproject.toml setup.py MANIFEST.in README.md LICENSE ./
COPY ibkr_report/ ./ibkr_report/
RUN pip3 install --no-cache-dir -e .[aws,docker,gcp]

# Optional local/debug stage: docker build --target test
FROM base AS test
COPY tests/ ./tests/
COPY requirements-dev.txt ./
RUN pip3 install --no-cache-dir -r requirements-dev.txt && \
    coverage run -m unittest discover && \
    coverage report -m

# Default production image (CI smoke + GHCR). Unit tests run on GitHub Actions runners.
FROM base AS prod
ENTRYPOINT []
CMD ["sh", "-c", "gunicorn --bind :$PORT --workers $GUNICORN_WORKERS --threads $GUNICORN_THREADS --timeout 0 main:app"]
