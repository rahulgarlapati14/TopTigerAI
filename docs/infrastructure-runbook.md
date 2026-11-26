# TopTigerAI inference infrastructure runbook

## Scope and accurate status

This repository contains deployment **configuration**, not proof of a live GPU deployment.
The default gateway uses a deterministic CPU mock. The optional GPU overlay
uses a pinned vLLM container and a small instruction model; it has not been
tested on an NVIDIA GPU in this project session.

## Prerequisites

- Docker Compose and NVIDIA GPU runtime/device access for local GPU experiments.
- A GPU with sufficient memory for model weights + KV cache + runtime overhead;
  an NVIDIA GPU with at least 8 GB VRAM is a pragmatic first experiment target,
  not a guarantee of compatibility.
- Network access to download the model, or a prepopulated and licensed model cache.
- Kubernetes deployment: cluster with NVIDIA device plugin, GPU nodes, working
  networking/storage, registry access, a metrics server (for gateway HPA), and
  optionally KEDA plus Prometheus for experimental GPU autoscaling.

## Local no-GPU smoke test

```bash
docker compose up --build -d
curl -fsS http://127.0.0.1:8001/health/ready
python benchmarks/inference_load.py --requests 50 --concurrency 5 --output /tmp/toptiger-mock.json
docker compose down
```

Mock mode tests proxy operation, not model throughput or GPU performance.

## Opt-in real GPU serving

```bash
export TOPTIGER_GATEWAY_KEY="replace-with-a-strong-random-secret"
export TOPTIGER_VLLM_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml up --build -d
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml logs -f vllm
curl -fsS http://127.0.0.1:8001/health/ready
TOPTIGER_GATEWAY_KEY="$TOPTIGER_GATEWAY_KEY" python benchmarks/inference_load.py --requests 50 --concurrency 5 --output /tmp/toptiger-gpu.json
```

First model download and GPU warm-up may take a long time. The vLLM container
port 8000 is not exposed to the host. Access the model through the gateway on
127.0.0.1:8001. **Do not expose this deployment on the public internet.**

The model is a general instruction model, not a fine-tuned boxing coach. The
gateway's instruction is conservative but output correctness is not established.
The presence of vLLM does not imply pose-analysis integration is enabled:
TOPTIGER_POSE_MODEL is still required on the worker.

## Kubernetes deployment

Review every manifest in `deploy/kubernetes/`. In particular, replace the
gateway image placeholder with your own built/pushed immutable image.

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl -n toptiger-inference create secret generic toptiger-inference-secrets \
  --from-literal=TOPTIGER_GATEWAY_KEY='REPLACE_WITH_RANDOM_SECRET'
kubectl apply -f deploy/kubernetes/configmap.yaml
kubectl apply -f deploy/kubernetes/vllm.yaml
kubectl apply -f deploy/kubernetes/gateway.yaml
kubectl apply -f deploy/kubernetes/networkpolicy.yaml
kubectl apply -f deploy/kubernetes/gateway-hpa.yaml
kubectl -n toptiger-inference get pods -w
kubectl -n toptiger-inference port-forward svc/inference-gateway 8001:8001
```

The manifest set is **not** a complete gym deployment: it excludes the
session API, database and video worker. Secrets management, RBAC, TLS, image
signatures, egress restrictions, object storage and network policy for the
gateway are future production work.

The optional `vllm-scaledobject.example.yaml` is **not** installed by default.
Before applying, verify your Prometheus URL and actual vLLM waiting-requests
metric name, deploy KEDA, ensure at least two suitable GPU nodes/accelerators
exist, and test scaling with real workload. Metric-based scaling is reactive,
so monitor model-start latency and queueing. HPA only scales CPU gateway replicas.

## Repeatable benchmark experiment

Run each configuration at fixed request count and concurrency, after warming
the model. Repeat at concurrency values 1, 2, 4 and 8, and record:

| Configuration | Requests | Success % | P50 latency | P95 latency | Requests/s |
|---|---:|---:|---:|---:|---:|
| CPU mock | — | — | — | — | — |
| vLLM / one GPU | — | — | — | — | — |
| vLLM / two GPUs | — | — | — | — | — |

Never fill unknown measurements with estimates. The included harness measures
**end-to-end non-streaming request latency** and successful requests/s. It
does **not** measure TTFT, tokens/s, GPU utilization or cost per token. For
those, add vLLM engine metrics, streaming instrumentation and GPU exporters.

## Failure injection plan

1. Record baseline p95 latency and success rate under steady load.
2. Kill one gateway pod; verify health checks and Service routing.
3. Kill one vLLM pod; measure unavailability and model cold-start recovery.
4. Saturate one GPU workload with requests; collect waiting queue metrics.
5. Restore traffic, inspect failed requests, and report recovery time.

Do not run destructive tests against shared or production clusters without
approval. Prometheus counters/gauges exist but no complete Grafana dashboard,
alerts, or externally verified cluster results are yet included.


## Release 6 — Actual streaming inference and pod recovery experiments

**These are runnable experiments, not reported GPU measurements.** No GPU,
Kubernetes cluster or customer-facing production environment was accessed by
the GitHub publishing process.

### 1. GPU inventory and baseline

On your dedicated GPU host, run:

```bash
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version --format=csv
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml up --build -d
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml logs --tail=100 vllm
curl -fsS http://127.0.0.1:8001/health/ready
```

Save the GPU type, VRAM, driver version, vLLM image tag, model ID, and
time-to-ready in your experiment notes. The gateway's health readiness
checks the vLLM health endpoint but does not itself measure a correct generation.

### 2. Port-forward the vLLM API **for the streaming benchmark only**

The GPU Compose configuration intentionally does not publish vLLM's API.
Use a dedicated Kubernetes test cluster to expose it to the local benchmark
through an authenticated / permitted port-forward:

```bash
kubectl --context <YOUR_TEST_CONTEXT> -n toptiger-inference \
  port-forward svc/vllm 8002:8000
```

Or, for the GPU Compose experiment, use a temporary localhost-only
publish override on your own controlled host. Do not publish vLLM to a
public interface or use an untrusted external endpoint.

In a second terminal, run a warm-up and a fixed-size experiment:

```bash
export TOPTIGER_VLLM_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
python benchmarks/vllm_streaming.py --url http://127.0.0.1:8002 --requests 3 --concurrency 1
python benchmarks/vllm_streaming.py --url http://127.0.0.1:8002 --requests 30 --concurrency 1 --output /tmp/toptiger-c1.json
python benchmarks/vllm_streaming.py --url http://127.0.0.1:8002 --requests 30 --concurrency 4 --output /tmp/toptiger-c4.json
python benchmarks/vllm_streaming.py --url http://127.0.0.1:8002 --requests 30 --concurrency 8 --output /tmp/toptiger-c8.json
```

Use `TOPTIGER_VLLM_API_KEY` if the server requires authentication.
The harness measures streamed **client-visible TTFT**, completed request
latency, and token rates when vLLM returns completion-token usage. The
generator uses fixed prompts and temperature 0. Results depend on hardware,
networking, tokens, and load; never compare different workloads as if they
were equivalent.

### 3. Kubernetes crash recovery (dedicated test cluster only)

The following command **deletes a real pod**. It requires an explicit context,
a fixed `toptiger-inference` namespace, a single ready `vllm` replica, and
the exact confirmation phrase. Do not run this on production clusters.

```bash
kubectl config get-contexts
python benchmarks/k8s_recovery.py \
  --context <YOUR_DEDICATED_TEST_CONTEXT> \
  --confirm DELETE_TEST_VLLM_POD \
  --timeout 600 \
  --output /tmp/toptiger-recovery.json
```

The test collects time until a *replacement* pod becomes Ready after
deleting its predecessor. It does not claim zero downtime or a successful
inference response. Combine this test with a separate bounded gateway
load run before/during/after the deletion to measure 5xx errors and recovery
as observed by clients.

### 4. Recording benchmark results

| Experiment | Hardware | Model | Concurrency | Success rate | P95 E2E | P95 TTFT | Output tok/sec |
|---|---|---|---:|---:|---:|---:|---:|
| Warmed baseline | Not measured | Not measured | 1 | — | — | — | — |
| Concurrent | Not measured | Not measured | 4 | — | — | — | — |
| Concurrent | Not measured | Not measured | 8 | — | — | — | — |

Store JSON output as reproducible experiment artifacts, *not* in a
public repository if it includes customer or infrastructure-sensitive data.
Do not treat the KEDA example as a validated autoscaler until a real
multi-GPU experiment confirms replica scheduling, prompt behavior and
latency changes.

### 5. Limitations still to address

- Kubernetes pod replacement is **not** the same as a controlled model
  rollout or a fault-tolerant multi-replica serving architecture.
- The vLLM Kubernetes pod uses an `emptyDir` model cache: replacement
  pods may re-download weights. Compare cold and warm starts fairly.
- The model size and vLLM version are pinned examples, not proof of
  compatibility with every GPU architecture.
- GPU utilization and GPU memory are not sampled by the Python benchmark;
  use NVIDIA SMI or DCGM exporter under explicit test conditions.
- Neither benchmark supplies real input validation for gym use, model
  evaluation against coach-reviewed labels, or production security.
