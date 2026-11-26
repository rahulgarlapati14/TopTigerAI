FROM python:3.12-slim AS base
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS pose-worker
COPY requirements-pose.txt .
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements-pose.txt
COPY app ./app
COPY static ./static

FROM base AS default
COPY app ./app
COPY static ./static
