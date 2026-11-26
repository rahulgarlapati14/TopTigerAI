# TopTigerAI

**Self-service AI boxing station — Release 3 prototype (recoverable jobs and observability)**

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

## Release 2: Experimental pose analysis (optional)

The default worker still returns upload and duration metadata, without pose analysis. To enable local analysis:

1. Install `pip install -r requirements-pose.txt`. The default Docker image does **not** bundle MediaPipe.
2. Obtain an approved **MediaPipe Pose Landmarker `.task` model** and comply with its licensing terms. See the [official Pose Landmarker guide](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker/python).
3. Set `TOPTIGER_POSE_MODEL=/absolute/path/to/pose_landmarker_lite.task` in the worker process environment.
4. Restart the worker and record a stable, full-body shadowboxing drill, at most **30 seconds**. Select left or right lead arm on the station before starting.

The analyzer decodes up to 10 frames/second, estimates 2D landmarks using MediaPipe Tasks, measures normalized lead-arm straightening, and counts extension-reset cycles with hysteresis. It abstains when too few pose landmarks are visible.

**Important:** Extension cycles are **not verified jab punches** and do not establish punch velocity, force, guard quality, or safe/correct technique. This is an experimental signal, not coach-approved feedback. Before a gym pilot, evaluate it against labeled footage across camera angles and users, and add coach review and privacy protections.

Run `python -m pytest -q` for the pure movement-logic unit tests (no MediaPipe required). Real video/model-asset integration has **not** been tested in CI.

**Infrastructure limitation:** SQLite plus the polling worker lacks job leasing and crash recovery. This prototype is not ready for exposure to real gym users or public internet traffic.


## Release 3: PostgreSQL, leased jobs, and Prometheus

### Run deployment locally (Docker)

```bash
docker compose up --build
```

API: http://localhost:8000 · API metrics: http://localhost:8000/metrics · Worker metrics: http://localhost:9101/metrics

The Docker setup uses **PostgreSQL 16**, a persistent database volume, and shared local video storage. It binds published service ports to localhost and uses deliberately insecure **development-only** database credentials. Do not deploy this Compose file onto a public server.

For Python development without Docker, SQLite remains the default:

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
# in another terminal
python -m app.worker
```

### Worker recovery behavior

- An atomic claim grants a 300-second lease to one worker.
- The worker refreshes its lease every 30 seconds while processing.
- A crashed worker's lease expires; another worker can claim its job.
- Completion checks the current worker ID, so an outdated worker cannot overwrite newer results.
- Processing exceptions queue a retry with a capped exponential delay, up to three attempts.
- After three attempts, jobs enter `failed` and remain inspectable by the session owner.
- Prometheus counters track claims, retries, successes and terminal failures. The API exports counts by job state.

### Verification

```bash
python -m pytest -q
```

The new local tests cover expired-lease recovery, stale-worker protection, capped retries, and basic metrics privacy. **15 tests passed locally with SQLite.** PostgreSQL integration and Docker Compose have not yet been executed in the development environment, so treat that deployment as needing verification.

### Production gaps

This is still an engineering prototype, not ready for live gym customers. There is no actual station authentication, secure multi-tenant isolation, encrypted object storage, media malware scanning, expiration-based deletion, durable job events, PostgreSQL migration tool, or LLM service. A real deployment needs secret management, authorized metrics access, video retention, safety review, worker resource limits, and meaningful video analysis evaluation. A lease permits **at-least-once execution**, not exactly-once execution; any external side effects must be made idempotent.
