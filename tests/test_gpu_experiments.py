"""Offline tests for streaming metrics and guarded Kubernetes recovery."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


stream = load("vllm_streaming", "benchmarks/vllm_streaming.py")
recovery = load("k8s_recovery", "benchmarks/k8s_recovery.py")


def test_streaming_sse_parser():
    assert stream.parse_sse_line(b": keepalive") is None
    assert stream.parse_sse_line(b"data: [DONE]") == "done"
    assert stream.parse_sse_line(b"data: {not json}") is None
    assert stream.parse_sse_line(b'data: {"choices": []}') == {"choices": []}


def test_local_only_model_url():
    assert stream.validate_origin("http://127.0.0.1:8002") == "http://127.0.0.1:8002"
    for bad in ("http://8.8.8.8:8000", "https://localhost:8002",
                "http://localhost:8002/foo", "http://user:secret@localhost:8002"):
        try:
            stream.validate_origin(bad)
            assert False, bad
        except ValueError:
            pass


def test_streaming_summary_and_missing_usage():
    rows = [
        {"status": 200, "e2e_ms": 100, "ttft_ms": 40,
         "completion_tokens": 11, "decode_tokens_per_second": 120},
        {"status": 200, "e2e_ms": 200, "ttft_ms": 60,
         "completion_tokens": 9, "decode_tokens_per_second": 100},
        {"status": 503},
    ]
    report = stream.summarize(rows, 2, {"model": "test"})
    assert report["successes"] == 2
    assert report["errors"] == {"503": 1}
    assert report["ttft_ms"]["p50"] == 50
    assert report["output_tokens_per_second_over_wall"] == 10
    assert report["successful_requests_per_second"] == 1
    rows[1]["completion_tokens"] = None
    assert stream.summarize(rows, 2, {})["output_tokens_per_second_over_wall"] is None


def test_recovery_readiness_and_identity():
    pod = {"metadata": {"uid": "new", "name": "vllm-new"},
           "status": {"phase": "Running",
                      "conditions": [{"type": "Ready", "status": "True"}]}}
    assert recovery.ready(pod)
    pod["metadata"]["deletionTimestamp"] = "2026-11-26T00:00:00Z"
    assert not recovery.ready(pod)


def test_recovery_requires_explicit_consent_without_cluster_call():
    try:
        recovery.experiment("any-context", "wrong", 60)
        assert False
    except ValueError as exc:
        assert "confirmation" in str(exc)


def test_target_verification_refuses_unexpected_replica_count(monkeypatch):
    calls = []

    def fake_kubectl(*args, **kwargs):
        calls.append(args)
        return {"spec": {"replicas": 2, "template": {"metadata": {
            "labels": {"app": "toptiger-vllm"}}}}}
    monkeypatch.setattr(recovery, "run_kubectl", fake_kubectl)
    try:
        recovery.verify_target("safe-test-context")
        assert False
    except ValueError as exc:
        assert "exactly one" in str(exc)
    assert len(calls) == 1
