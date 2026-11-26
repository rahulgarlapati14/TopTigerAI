# TopTigerAI

**Self-service AI boxing station — Release 1 (video ingestion prototype)**

TopTigerAI is a boxing-gym station and an engineering portfolio for Forward Deployed Engineering and inference infrastructure.

## What currently works

- Mobile-friendly gym station at `/` (optional `?station=demo-station`).
- Explicit adult recording consent and per-session random access tokens.
- MP4/WebM uploads up to 25 MB, header check, duplicate upload rejection.
- Persistent local SQLite sessions and private local video files.
- Separate worker processing queued sessions, reading video metadata using optional `ffprobe`.
- Polling of job status, deletion, Docker Compose, API tests.

**This release does not analyze boxing technique and is not production-ready. Do not pilot with real customer footage yet.**

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
# In a second terminal:
python -m app.worker
```

Visit http://localhost:8000 or run `docker compose up --build`.

## Tests

```bash
python -m pytest -q
```

## Architecture

Browser → FastAPI session/upload API → SQLite and local uploads → polling worker → status/result.

## Roadmap

1. Harden station authentication, uploads, PostgreSQL, S3-compatible storage, privacy, retention and job recovery.
2. Add controlled boxing-drill dataset, pose extraction and coach-validated technique feedback.
3. Add multi-tenant gym authorization, OIDC staff login, audit logs, Temporal review workflows and replay evaluation.
4. Add vLLM, Kubernetes/Helm, Prometheus/OpenTelemetry, GPU autoscaling, load tests and failure injection.
5. Conduct an opt-in gym pilot with product and operational metrics.

## Limitations

There is no production identity, tenant security, malware scanning, full media decoding validation, encrypted storage, automatic retention, or crash-resilient workflow recovery. The demo API must not be exposed to the public internet. Record only consenting adults with permission and no bystanders.

See the source files for implementation details.