"""GPU inference streaming benchmark against a loopback-only vLLM endpoint.

Measures actual streamed TTFT, end-to-end latency and generated tokens/sec.
Requires a running vLLM OpenAI-compatible server, e.g. via kubectl port-forward.
Use only with infrastructure you own or have permission to benchmark.

No remote/public hosts are accepted. Output is aggregated, not prompts or tokens.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def validate_origin(origin: str) -> str:
    parts = urlparse(origin)
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost")
            or parts.username or parts.password or parts.path not in ("", "/")
            or parts.query or parts.fragment or not parts.port):
        raise ValueError("Use a local HTTP origin with a port (such as http://127.0.0.1:8002)")
    return origin.rstrip("/")


def pct(values: list[float], p: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p / 100
    low, high = int(rank), min(math.ceil(rank), len(ordered) - 1)
    return ordered[low] * (high - rank) + ordered[high] * (rank - low) if low != high else ordered[low]


def parse_sse_line(line: bytes):
    """Ignore metadata/comments; return dict, sentinel, or None."""
    if not line.startswith(b"data:"):
        return None
    data = line[5:].strip()
    if data == b"[DONE]":
        return "done"
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def run_once(origin: str, model: str, api_key: str, timeout: float,
             max_tokens: int, prompt: str) -> dict:
    req_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer concisely in plain English."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = Request(origin + "/v1/chat/completions",
                      data=json.dumps(req_body).encode(),
                      headers=headers, method="POST")
    start = time.perf_counter()
    first_token = None
    completion_tokens = None
    observed_chunks = 0
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return {"status": response.status}
            for raw in response:
                event = parse_sse_line(raw.strip())
                if event == "done":
                    break
                if not isinstance(event, dict):
                    continue
                usage = event.get("usage")
                if isinstance(usage, dict) and isinstance(usage.get("completion_tokens"), int):
                    completion_tokens = usage["completion_tokens"]
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    # Time of first nonempty text content, not initial empty SSE chunk.
                    if isinstance(delta.get("content"), str) and delta["content"]:
                        observed_chunks += 1
                        if first_token is None:
                            first_token = time.perf_counter()
            end = time.perf_counter()
            result = {"status": 200,
                      "e2e_ms": round((end - start) * 1000, 3),
                      "ttft_ms": round((first_token - start) * 1000, 3) if first_token is not None else None,
                      "completion_tokens": completion_tokens,
                      "observed_text_chunks": observed_chunks}
            if first_token is not None and completion_tokens and completion_tokens > 1 and end > first_token:
                result["decode_tokens_per_second"] = round((completion_tokens - 1) / (end - first_token), 3)
            else:
                result["decode_tokens_per_second"] = None
            return result
    except HTTPError as exc:
        status = exc.code
        exc.close()
        return {"status": status}
    except (URLError, TimeoutError, OSError, ValueError):
        return {"status": "connection_error"}


def summarize(results: list[dict], elapsed: float, config: dict) -> dict:
    successful = [r for r in results if r.get("status") == 200]
    errors: dict[str, int] = {}
    for row in results:
        if row.get("status") != 200:
            code = str(row.get("status", "unknown"))
            errors[code] = errors.get(code, 0) + 1
    def stats(key):
        values = [r[key] for r in successful if isinstance(r.get(key), (int, float))]
        return {
            "samples": len(values),
            "mean": round(statistics.mean(values), 3) if values else None,
            "p50": round(pct(values, 50), 3) if values else None,
            "p95": round(pct(values, 95), 3) if values else None,
            "p99": round(pct(values, 99), 3) if values else None,
        }
    token_counts = [r["completion_tokens"] for r in successful
                    if isinstance(r.get("completion_tokens"), int)]
    return {
        "configuration": config,
        "attempted_requests": len(results),
        "successes": len(successful),
        "errors": errors,
        "success_rate": round(len(successful) / len(results), 4) if results else None,
        "wall_seconds": round(elapsed, 3),
        "successful_requests_per_second": round(len(successful) / elapsed, 3) if elapsed else None,
        "output_tokens_per_second_over_wall": round(sum(token_counts) / elapsed, 3)
        if len(token_counts) == len(successful) and elapsed and successful else None,
        "e2e_latency_ms": stats("e2e_ms"),
        "ttft_ms": stats("ttft_ms"),
        "per_request_decode_tokens_per_second": stats("decode_tokens_per_second"),
        "limitations": (
            "Streamed TTFT measures first nonempty text arrival at client (includes network overhead). "
            "Decode rate assumes usage completion_tokens accurately reflects generated tokens. "
            "Aggregate output tokens/s is omitted if upstream does not provide usage. "
            "No GPU memory or cost metrics are collected here."
        ),
    }


def run_benchmark(origin: str, model: str, api_key: str, requests: int,
                  concurrency: int, timeout: float, max_tokens: int, prompt: str) -> dict:
    validate_origin(origin)
    if not 1 <= requests <= 1000 or not 1 <= concurrency <= 32:
        raise ValueError("requests must be 1–1000 and concurrency 1–32")
    if not 16 <= max_tokens <= 512 or not 1 <= timeout <= 180:
        raise ValueError("max_tokens must be 16–512 and timeout 1–180s")
    if not model or len(model) > 200 or not 1 <= len(prompt) <= 2000:
        raise ValueError("invalid model or prompt length")
    config = {"model": model, "requests": requests, "concurrency": concurrency,
              "max_tokens": max_tokens, "timeout_seconds": timeout}
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(run_once, origin, model, api_key, timeout, max_tokens, prompt)
                   for _ in range(requests)]
        results = [f.result() for f in as_completed(futures)]
    return summarize(results, time.perf_counter() - start, config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8002")
    parser.add_argument("--model", default=os.getenv("TOPTIGER_VLLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"))
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    prompt = "Explain why a consistent camera angle matters when recording a boxing jab drill. Do not assess technique."
    report = run_benchmark(args.url, args.model, os.getenv("TOPTIGER_VLLM_API_KEY", ""),
                           args.requests, args.concurrency, args.timeout, args.max_tokens, prompt)
    payload = json.dumps(report, indent=2) + "\n"
    print(payload, end="")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as out:
            out.write(payload)


if __name__ == "__main__":
    main()
