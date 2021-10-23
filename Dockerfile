FROM python:3.10.0-slim AS base

ARG DEBIAN_FRONTEND=noninteractive

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True
ENV APP_HOME /app
ENV GUNICORN_WORKERS 1
ENV GUNICORN_THREADS 8
ENV PORT 8080

WORKDIR $APP_HOME
COPY main.py requirements.txt ./
COPY static/ ./static/
COPY templates/ ./templates/
RUN pip3 install --no-cache-dir -r requirements.txt

FROM base AS test
COPY test-data/ ./test-data/
COPY test.py requirements-dev.txt ./
RUN pip3 install --no-cache-dir -r requirements-dev.txt && \
    coverage run --source=./ --omit=test.py test.py && \
    coverage report -m

FROM base AS prod
ENTRYPOINT []
CMD exec gunicorn --bind :$PORT --workers $GUNICORN_WORKERS --threads $GUNICORN_THREADS --timeout 0 main:app
