"""Opt-in Kubernetes cold-start recovery experiment on a dedicated test namespace.

Never run on customer/production clusters. This intentionally deletes one
vLLM pod and observes replacement readiness. It does not prove zero downtime.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


NAMESPACE = "toptiger-inference"
SELECTOR = "app=toptiger-vllm"
CONSENT = "DELETE_TEST_VLLM_POD"


def run_kubectl(*args: str, timeout: int = 15) -> dict:
    result = subprocess.run(["kubectl", *args], capture_output=True, text=True,
                            check=True, timeout=timeout)
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # kubectl delete prints human-readable acknowledgement, not JSON
        return {"message": result.stdout.strip()}


def get_pods(context: str) -> list[dict]:
    doc = run_kubectl("--context", context, "-n", NAMESPACE, "get", "pods",
                      "-l", SELECTOR, "-o", "json")
    return doc.get("items", [])


def ready(pod: dict) -> bool:
    conditions = pod.get("status", {}).get("conditions", [])
    return pod.get("status", {}).get("phase") == "Running" and any(
        c.get("type") == "Ready" and c.get("status") == "True" for c in conditions
    ) and pod.get("metadata", {}).get("deletionTimestamp") is None


def verify_target(context: str) -> dict:
    # A named, explicit context prevents accidental use of whatever kubectl defaults to.
    if not context or len(context) > 200:
        raise ValueError("A named Kubernetes context is mandatory")
    deployment = run_kubectl("--context", context, "-n", NAMESPACE,
                             "get", "deployment", "vllm", "-o", "json")
    template_labels = deployment["spec"]["template"]["metadata"]["labels"]
    if template_labels.get("app") != "toptiger-vllm" or deployment["spec"]["replicas"] != 1:
        raise ValueError("Experiment requires exactly one dedicated toptiger-vllm replica")
    pods = get_pods(context)
    if len(pods) != 1 or not ready(pods[0]):
        raise ValueError("Experiment requires exactly one currently ready vLLM pod")
    return pods[0]


def observe_replacement(context: str, old_uid: str, max_seconds: int, poll_interval: float = 2):
    start = time.monotonic()
    samples = []
    while time.monotonic() - start <= max_seconds:
        pods = get_pods(context)
        replacements = [p for p in pods
                        if p["metadata"]["uid"] != old_uid and ready(p)]
        elapsed = round(time.monotonic() - start, 3)
        samples.append({"elapsed_seconds": elapsed,
                        "ready_replacement": bool(replacements),
                        "observed_pod_count": len(pods)})
        if replacements:
            return {"recovered": True, "recovery_seconds": elapsed, "samples": samples}
        time.sleep(poll_interval)
    return {"recovered": False, "recovery_seconds": None, "samples": samples}


def experiment(context: str, consent: str, max_seconds: int) -> dict:
    if consent != CONSENT:
        raise ValueError(f"Explicit confirmation required: --confirm {CONSENT}")
    if not 30 <= max_seconds <= 900:
        raise ValueError("Timeout must be 30–900 seconds")
    target = verify_target(context)
    uid = target["metadata"]["uid"]
    name = target["metadata"]["name"]
    recorded_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    # Kubernetes controller should replace the pod. Default graceful deletion
    # minimizes disruption compared to forcibly killing an unrelated process.
    run_kubectl("--context", context, "-n", NAMESPACE, "delete", "pod", name,
                "--wait=false", timeout=20)
    measured = observe_replacement(context, uid, max_seconds)
    return {
        "experiment": "single_replica_vllm_pod_deletion",
        "context": context,
        "namespace": NAMESPACE,
        "old_pod_name": name,
        "old_pod_uid": uid,
        "started_at": recorded_at,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        **measured,
        "limitations": (
            "Measures pod Ready recovery only, not end-to-end service availability, "
            "lost requests, or successful generation. Combine with a separate load test "
            "for user-visible failure impact."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = experiment(args.context, args.confirm, args.timeout)
    payload = json.dumps(report, indent=2) + "\n"
    print(payload, end="")
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
