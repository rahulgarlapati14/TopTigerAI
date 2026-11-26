"""Pure benchmark mathematics and safety tests (no running server needed)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "inference_load",
    Path(__file__).resolve().parents[1] / "benchmarks" / "inference_load.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_percentiles_interpolate():
    assert module.percentile([100, 200, 300], 50) == 200
    assert module.percentile([100, 200], 95) == 195
    assert module.percentile([], 95) is None


def test_summary_successes_and_errors():
    results = [
        {"status": 200, "latency_ms": 50},
        {"status": 200, "latency_ms": 100},
        {"status": 503, "latency_ms": 200},
    ]
    report = module.summarize(results, 1)
    assert report["requests"] == 3
    assert report["successes"] == 2
    assert report["errors"] == {"503": 1}
    assert report["requests_per_second"] == 2
    assert report["latency_ms"]["p50"] == 75


def test_benchmark_restricts_target_to_loopback():
    for target in ["https://some-website.com", "http://192.168.1.3:8001", "http://127.0.0.1:8001/admin"]:
        try:
            module.validate_url(target)
            assert False, target
        except ValueError:
            pass
    assert module.validate_url("http://localhost:8001") == "http://localhost:8001"
