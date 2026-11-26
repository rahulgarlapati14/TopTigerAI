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


## Release 4: Inference Gateway (CPU mock / optional vLLM)

A standalone FastAPI gateway now exposes `POST /v1/feedback` with a **strict JSON schema**, internal bearer-token authentication, capped generation settings, and a fixed operator-configured vLLM upstream. It accepts structured pose observations only, **not raw boxing footage or identities**. The gateway provides `/health/live`, `/health/ready` and Prometheus `/metrics` endpoints. Metrics contain only static bounded-cardinality labels, never user text or session tokens.

### Run the gateway without a GPU

```bash
docker compose up --build
# Separate terminal:
curl -s http://127.0.0.1:8001/health/ready
curl -s -X POST http://127.0.0.1:8001/v1/feedback \
  -H 'Authorization: Bearer local-dev-gateway-key' \
  -H 'Content-Type: application/json' \
  -d '{"observations":{"lead_arm":"left","extension_cycle_candidates":3,"usable_frame_fraction":0.9,"duration_seconds":10,"technique_analyzed":false}}'
```

This default mode emits deterministic, conservative mock feedback. It makes **no LLM request** and requires no GPU. The worker will call the gateway only when experimental MediaPipe pose analysis is enabled; plain video-ingestion jobs remain unchanged. The gym station labels its feedback **experimental and not coach-reviewed**.

### Connect a real local vLLM instance

First serve an operator-selected, compatible instruction model using vLLM's OpenAI-compatible server, with the actual served model ID configured. Then set these deployment environment values in the `inference-gateway` service:

```text
TOPTIGER_INFERENCE_BACKEND=vllm
TOPTIGER_VLLM_URL=http://vllm:8000
TOPTIGER_VLLM_MODEL=<exact-model-id-served-by-vllm>
TOPTIGER_GATEWAY_KEY=<strong-internal-secret>
TOPTIGER_VLLM_API_KEY=<optional-upstream-auth-key>
```

The `vllm` hostname must resolve to an actual network-reachable vLLM service. **The Compose file does not provision any vLLM server, GPU, model weights, NVIDIA drivers, or Kubernetes resources.** Running in `vllm` mode without a live upstream will result in failed readiness and 503 inference responses.

For a local non-Docker gateway run:

```bash
TOPTIGER_GATEWAY_KEY=dev-secret uvicorn app.inference_gateway:app --port 8001
```

The gateway does not accept user-selected URLs or model names. vLLM transport failures return sanitized 503 errors without leaking upstream response bodies. A single retry can duplicate billed model work, so automatic inference retries are deliberately not implemented.

### Contract tests

```bash
python -m pytest -q tests/test_inference_gateway.py
```

The tests cover authentication, conservative mock output, missing-pose abstention, input limits, health endpoints, and metrics. **Real GPU/vLLM integration, load tests, and Docker end-to-end validation remain outstanding.**

### Known limitations

This is **not** production-ready. Bearer tokens must be provisioned and rotated securely; production deployments must restrict metrics, health and gateway ingress to trusted networks and enforce TLS. Gateway readiness does not prove model accuracy. Untrusted user notes could still attempt prompt injection when vLLM is enabled, so use a vetted model with output validation, ground-truth evaluations and human coach review. The `supported_by_observations: false` field deliberately does not certify an LLM response. Do not expose this service to gym members or treat generated content as authoritative boxing coaching.
