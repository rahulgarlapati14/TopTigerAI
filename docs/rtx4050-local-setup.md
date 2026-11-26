# RTX 4050: first real GPU inference experiment

This runbook targets the **RTX 4050 Laptop GPU with 6 GB VRAM**.
NVIDIA GPU variants can differ: verify the exact device and memory using
`nvidia-smi` before using these commands.

## Why this configuration

6 GB VRAM is tight for model weights, KV cache, CUDA runtime and desktop use.
Start with a 0.5B instruction model, a 1,024-token context limit,
2 simultaneous sequences and 70% target GPU memory utilization.
These are initial conservative settings, not guaranteed to fit on every laptop.
Do **not** begin with 7B/8B full-precision models.

## Windows 11 / Windows 10 (WSL2)

Use Docker Desktop's **WSL2 backend with Linux containers**, a current
NVIDIA Windows driver and an up-to-date WSL2 installation.

In PowerShell:

```powershell
nvidia-smi
wsl --update
wsl --status
docker version
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu22.04 nvidia-smi
```

The CUDA image is only a GPU-pass-through smoke test. If the sample image
tag is unavailable, select an existing official CUDA base image tag.
You do **not** have to install a second NVIDIA Linux display driver inside WSL2.

## Linux with NVIDIA Container Toolkit

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu22.04 nvidia-smi
```

If the Docker test fails, configure NVIDIA Container Toolkit before
trying vLLM. Do not run load tests until the GPU is visible inside containers.

## Clone and run in mock mode first

```bash
git clone https://github.com/rahulgarlapati14/TopTigerAI.git
cd TopTigerAI
docker compose up -d --build
curl http://127.0.0.1:8001/health/ready
```

Expected: `{"status":"ready","backend":"mock"}`.

## Switch to local RTX 4050 serving

Start a small model with the base GPU overlay and low-VRAM override:

```bash
export TOPTIGER_GATEWAY_KEY='local-dev-change-this-key'
export TOPTIGER_VLLM_MODEL='Qwen/Qwen2.5-0.5B-Instruct'

docker compose -f docker-compose.yml \
  -f deploy/gpu/docker-compose.gpu.yml \
  -f deploy/gpu/docker-compose.rtx4050.yml \
  up -d --build
```

PowerShell equivalents for the environment variables:

```powershell
$env:TOPTIGER_GATEWAY_KEY='local-dev-change-this-key'
$env:TOPTIGER_VLLM_MODEL='Qwen/Qwen2.5-0.5B-Instruct'
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml -f deploy/gpu/docker-compose.rtx4050.yml up -d --build
```

Follow model startup:

```bash
docker compose -f docker-compose.yml -f deploy/gpu/docker-compose.gpu.yml -f deploy/gpu/docker-compose.rtx4050.yml logs --tail=80 -f vllm
```

On the first run the image and weights may need downloading. Check:

```bash
curl http://127.0.0.1:8001/health/ready
nvidia-smi
```

Expected readiness: `backend=vllm` once the upstream actually starts.

If the GPU is out of memory, stop games and other GPU applications;
reduce `--gpu-memory-utilization` and `--max-num-seqs` or consider a
smaller/quantized compatible model. Low VRAM itself is not evidence of
an infrastructure software failure.

## Benchmark the gateway

Use small, repeatable concurrency values and record real measurements:

```bash
python benchmarks/inference_load.py --requests 10 --concurrency 1 --output rtx4050-c1.json
python benchmarks/inference_load.py --requests 20 --concurrency 2 --output rtx4050-c2.json
```

For **streamed TTFT and decoded tokens/sec**, run the dedicated streaming
benchmark on a local port-forward to the vLLM server, rather than the
gateway (the gateway currently uses non-streaming requests). This
requires an explicitly permitted localhost-only forwarding setup; see
`docs/infrastructure-runbook.md`.

Never invent throughput figures. Compare same model, prompt length, output
tokens, and warmup procedure. Capture `nvidia-smi` alongside JSON results
if you want to compare memory use and utilization.

## Caveats

- RTX 4050 laptop configurations are generally 6 GB; check actual VRAM.
- vLLM is not natively supported on Windows; Docker Linux containers with
  WSL2 or a Linux host are the intended options.
- This overlay is not a measured successful deployment.
- GPU run configuration requires the host to supply working drivers,
  Docker GPU integration and network access for model weights.
- The project is still a prototype. Do not expose upload, metrics or
  generation endpoints to an untrusted network.
