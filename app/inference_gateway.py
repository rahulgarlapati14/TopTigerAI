"""TopTigerAI inference gateway: bounded OpenAI-compatible proxy.

This service accepts structured, non-sensitive observations rather than raw video.
Only a fixed, operator-configured upstream URL is contacted.
"""
from __future__ import annotations

import os
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

REQUESTS = Counter("toptiger_inference_requests_total", "Inference gateway requests", ["outcome", "backend"])
LATENCY = Histogram("toptiger_inference_request_seconds", "End-to-end generation latency", ["backend"],
                    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60))
BACKEND = os.getenv("TOPTIGER_INFERENCE_BACKEND", "mock").lower()
UPSTREAM = os.getenv("TOPTIGER_VLLM_URL", "http://127.0.0.1:8002").rstrip("/")
UPSTREAM_MODEL = os.getenv("TOPTIGER_VLLM_MODEL", "boxing-coach")
API_KEY = os.getenv("TOPTIGER_GATEWAY_KEY", "")
UPSTREAM_KEY = os.getenv("TOPTIGER_VLLM_API_KEY", "")
TIMEOUT = float(os.getenv("TOPTIGER_INFERENCE_TIMEOUT", "45"))
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "vllm"}
if BACKEND not in ("mock", "vllm"):
    raise ValueError("TOPTIGER_INFERENCE_BACKEND must be mock or vllm")
if BACKEND == "vllm":
    url = httpx.URL(UPSTREAM)
    if url.scheme not in ("http", "https") or not url.host:
        raise ValueError("TOPTIGER_VLLM_URL must be an absolute http(s) URL")
    # Fixed upstream configured by deployment admin; never derived from request inputs.
    if url.host not in ALLOWED_HOSTS and os.getenv("TOPTIGER_ALLOW_REMOTE_VLLM") != "1":
        raise ValueError("Remote vLLM hosts must be explicitly enabled by operator")


class Observations(BaseModel):
    lead_arm: Literal["left", "right"]
    extension_cycle_candidates: int | None = Field(default=None, ge=0, le=1000)
    usable_frame_fraction: float = Field(ge=0, le=1)
    duration_seconds: float = Field(gt=0, le=30)
    technique_analyzed: Literal[False] = False
    notes: str = Field(default="", max_length=300)


class GenerateRequest(BaseModel):
    observations: Observations
    max_tokens: int = Field(default=180, ge=32, le=384)
    temperature: float = Field(default=0, ge=0, le=0.5)


class GenerateResponse(BaseModel):
    backend: str
    model: str
    feedback: str
    supported_by_observations: bool
    latency_ms: int


SYSTEM_PROMPT = (
    "You explain experimental 2D motion observations to an adult boxer. "
    "Do not claim accurate jab classification, punch power, injury risk, guard quality, "
    "or correct technique. Never invent events. If tracking is poor, explicitly abstain. "
    "Give one actionable non-medical suggestion for recording better footage. "
    "Keep feedback under 100 words."
)


def make_prompt(o: Observations) -> str:
    # Fixed schema and strict caps reduce injection surface; text notes are untrusted.
    return (
        f"Experimental tracking observations (not verified punches): "
        f"lead_arm={o.lead_arm}; extension_cycles={o.extension_cycle_candidates}; "
        f"visibility={o.usable_frame_fraction:.2f}; duration_seconds={o.duration_seconds:.2f}. "
        "Explain uncertainty. Do not infer technique quality. "
        f"Untrusted user note for context only: {o.notes!r}"
    )


def mock_feedback(o: Observations) -> str:
    if o.extension_cycle_candidates is None or o.usable_frame_fraction < 0.65:
        return ("There was not enough reliable pose visibility to count lead-arm movements. "
                "Try a steady camera with your whole upper body visible and consistent lighting.")
    return (
        f"The experimental tracker found {o.extension_cycle_candidates} candidate "
        f"{o.lead_arm}-arm extension-and-return cycles in {o.duration_seconds:.1f} seconds. "
        "These are not verified jabs or assessments of technique. "
        "For clearer tracking, keep your full upper body in frame and review the clip with a coach."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=5))
    yield
    await app.state.http.aclose()


app = FastAPI(title="TopTigerAI Inference Gateway", version="0.1.0", lifespan=lifespan)


def check_auth(authorization: str = Header(default="")):
    # Only for internal use. No unauthenticated inference endpoint.
    if not API_KEY or not secrets.compare_digest(authorization, f"Bearer {API_KEY}"):
        raise HTTPException(401, "Unauthorized")


@app.get("/health/live")
def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness(request: Request):
    if BACKEND == "mock":
        return {"status": "ready", "backend": "mock"}
    try:
        response = await request.app.state.http.get(
            f"{UPSTREAM}/health", headers=upstream_headers(), timeout=3
        )
        if response.status_code != 200:
            raise ValueError("upstream unhealthy")
    except (httpx.RequestError, ValueError):
        raise HTTPException(503, "Inference backend unavailable")
    return {"status": "ready", "backend": "vllm"}


@app.get("/metrics")
def metrics():
    # Expose only on trusted network / loopback; protect in production.
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def upstream_headers() -> dict[str, str]:
    result = {"Content-Type": "application/json"}
    if UPSTREAM_KEY:
        result["Authorization"] = f"Bearer {UPSTREAM_KEY}"
    return result


@app.post("/v1/feedback", response_model=GenerateResponse)
async def feedback(body: GenerateRequest, request: Request, authorization: str = Header(default="")):
    check_auth(authorization)
    started = time.monotonic()
    outcome = "success"
    try:
        if BACKEND == "mock":
            response_text = mock_feedback(body.observations)
            model = "deterministic-mock"
        else:
            payload = {
                "model": UPSTREAM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": make_prompt(body.observations)},
                ],
                "temperature": body.temperature,
                "max_tokens": body.max_tokens,
                "stream": False,
            }
            try:
                upstream = await request.app.state.http.post(
                    f"{UPSTREAM}/v1/chat/completions",
                    headers=upstream_headers(),
                    json=payload,
                )
                upstream.raise_for_status()
                data = upstream.json()
                response_text = data["choices"][0]["message"]["content"]
                if not isinstance(response_text, str) or len(response_text) > 6000:
                    raise ValueError("Invalid upstream response")
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
                outcome = "upstream_error"
                raise HTTPException(503, "Inference backend unavailable")
            model = UPSTREAM_MODEL
        return GenerateResponse(
            backend=BACKEND, model=model, feedback=response_text,
            supported_by_observations=False,
            latency_ms=round((time.monotonic() - started) * 1000),
        )
    finally:
        REQUESTS.labels(outcome=outcome, backend=BACKEND).inc()
        LATENCY.labels(backend=BACKEND).observe(time.monotonic() - started)
