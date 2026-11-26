# Windows PowerShell: RTX 4060 streaming inference benchmark

This is an opt-in **local development only** benchmark. It connects directly
to vLLM (rather than the non-streaming inference gateway) so it can measure
time-to-first-token (TTFT) and generated tokens/second.

## 1. Update source and confirm the actual backend

Open PowerShell at `C:\Users\rahul\TopTigerAI`:

```powershell
git pull origin main
curl.exe http://127.0.0.1:8001/health/ready
```

Confirm `"backend":"vllm"` before attributing prior gateway metrics
to GPU inference. If it returns `"mock"`, earlier gateway results did
not measure GPU inference.

## 2. Expose raw vLLM on loopback temporarily

Your currently running configuration uses an RTX 4050-named low-VRAM
overlay. That overlay also works as a conservative baseline on an RTX 4060.

```powershell
$env:TOPTIGER_GATEWAY_KEY="local-dev-gateway-key"
$env:TOPTIGER_VLLM_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml -f deploy/gpu/docker-compose.rtx4050.yml -f deploy/gpu/docker-compose.benchmark.yml up -d
```

The benchmark override publishes the raw vLLM server only at
`127.0.0.1:8002`. It is intentionally not exposed on your LAN.

Verify model availability (PowerShell):

```powershell
curl.exe http://127.0.0.1:8002/health
curl.exe http://127.0.0.1:8002/v1/models
```

The `/v1/models` response must contain the same model ID used in
`TOPTIGER_VLLM_MODEL`.

## 3. Run streaming tests with identical workloads

```powershell
$env:TOPTIGER_VLLM_MODEL="Qwen/Qwen2.5-0.5B-Instruct"
python benchmarks/vllm_streaming.py --requests 3 --concurrency 1
python benchmarks/vllm_streaming.py --requests 30 --concurrency 1 --output rtx4060-stream-c1.json
python benchmarks/vllm_streaming.py --requests 30 --concurrency 2 --output rtx4060-stream-c2.json
python benchmarks/vllm_streaming.py --requests 30 --concurrency 4 --output rtx4060-stream-c4.json
```

The `rtx4050` overlay currently limits `--max-num-seqs` to 2, meaning
concurrency 4 may queue requests. Queueing is worth measuring but should not
be mistaken for a hard GPU concurrency limit. Keep the model, max output
tokens, prompt and warmup fixed for comparisons.

Collect GPU state in another PowerShell window during the test:

```powershell
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,power.draw --format=csv -l 1
```

Stop with Ctrl+C. The streaming script reports client-visible TTFT,
end-to-end latency and token rates *only when usage metadata is available*.
The results are not model accuracy, boxing quality or cost measurements.

## 4. Remove temporary vLLM exposure

After the experiment:

```powershell
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml -f deploy/gpu/docker-compose.rtx4050.yml up -d --force-recreate
```

Verify that `http://127.0.0.1:8002/health` is no longer reachable.
If Docker Compose reports a persistent port mapping, use
`docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml -f deploy/gpu/docker-compose.rtx4050.yml down`
then `up -d` with only those three files. Avoid `down -v` because it
deletes database, video and model cache volumes.

## Interpretation

Prior 70 requests at mixed request counts/concurrencies are a promising
smoke test, **not** a controlled saturation study. At concurrency 4,
the baseline overlay's `--max-num-seqs 2` may limit execution parallelism.
Repeat identical-size tests multiple times and capture the model ID,
GPU memory, driver, success/error counts and P50/P95/P99 before drawing
performance conclusions.
