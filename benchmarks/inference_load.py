"""Bounded, opt-in inference-gateway load test.

Example:
  python benchmarks/inference_load.py --url http://127.0.0.1:8001 --requests 50 --concurrency 5
Outputs real measurements; never generates benchmark scores in advance.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def percentile(sorted_values: list[float], percentile_value: float) -> float | None:
    if not sorted_values:
        return None
    rank = (len(sorted_values) - 1) * percentile_value / 100
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize(results: list[dict], wall_seconds: float) -> dict:
    success = sorted(r["latency_ms"] for r in results if r["status"] == 200)
    errors: dict[str, int] = {}
    for r in results:
        if r["status"] != 200:
            k = str(r["status"])
            errors[k] = errors.get(k, 0) + 1
    return {
        "requests": len(results),
        "successes": len(success),
        "errors": errors,
        "wall_seconds": round(wall_seconds, 3),
        "requests_per_second": round(len(success) / wall_seconds, 3) if wall_seconds > 0 else None,
        "latency_ms": {
            "mean": round(statistics.mean(success), 2) if success else None,
            "p50": round(percentile(success, 50), 2) if success else None,
            "p95": round(percentile(success, 95), 2) if success else None,
            "p99": round(percentile(success, 99), 2) if success else None,
        },
        "note": "End-to-end gateway latency only; not TTFT or tokens/sec.",
    }


def request_once(url: str, key: str, timeout: float) -> dict:
    payload = {
        "observations": {
            "lead_arm": "left",
            "extension_cycle_candidates": 4,
            "usable_frame_fraction": 0.94,
            "duration_seconds": 12.0,
            "technique_analyzed": False,
        },
        "max_tokens": 128,
        "temperature": 0,
    }
    request = Request(
        url.rstrip("/") + "/v1/feedback",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read()
            return {"status": response.status, "latency_ms": (time.perf_counter() - start) * 1000}
    except HTTPError as exc:
        exc.close()
        return {"status": exc.code, "latency_ms": (time.perf_counter() - start) * 1000}
    except (URLError, TimeoutError, OSError):
        return {"status": "connection_error", "latency_ms": (time.perf_counter() - start) * 1000}


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or parsed.username or parsed.password:
        raise ValueError("Benchmark intentionally restricted to local HTTP gateway")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Pass just the gateway origin, not a path")
    return url.rstrip("/")


def run(url: str, key: str, count: int, concurrency: int, timeout: float) -> dict:
    if count < 1 or count > 10000 or concurrency < 1 or concurrency > 64:
        raise ValueError("Requests must be 1–10000 and concurrency 1–64")
    url = validate_url(url)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(request_once, url, key, timeout) for _ in range(count)]
        results = [future.result() for future in as_completed(futures)]
    return summarize(results, time.perf_counter() - start)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    key = os.getenv("TOPTIGER_GATEWAY_KEY", "local-dev-gateway-key")
    report = run(args.url, key, args.requests, args.concurrency, args.timeout)
    output = json.dumps(report, indent=2)
    print(output)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            file.write(output + "\n")


if __name__ == "__main__":
    main()
