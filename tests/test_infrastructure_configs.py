"""Static deployment assertions. These do not prove a GPU cluster is working."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def documents(path):
    return [x for x in yaml.safe_load_all((ROOT / path).read_text()) if x]


def test_gpu_compose_opt_in_and_vllm_internal():
    overlay = documents("deploy/gpu/docker-compose.gpu.yml")[0]
    gateway = overlay["services"]["inference-gateway"]
    vllm = overlay["services"]["vllm"]
    assert gateway["environment"]["TOPTIGER_INFERENCE_BACKEND"] == "vllm"
    assert "ports" not in vllm  # Not host-exposed.
    devices = vllm["deploy"]["resources"]["reservations"]["devices"]
    assert devices[0]["capabilities"] == ["gpu"]
    assert devices[0]["count"] == 1


def test_gpu_deployment_has_resources_and_health_probes():
    deploy, service = documents("deploy/kubernetes/vllm.yaml")
    assert deploy["kind"] == "Deployment"
    assert service["kind"] == "Service"
    assert service["spec"]["type"] == "ClusterIP"
    container = deploy["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert "startupProbe" in container
    assert "readinessProbe" in container
    assert "livenessProbe" in container


def test_gateway_requires_secret_and_internal_service():
    deploy, service = documents("deploy/kubernetes/gateway.yaml")
    container = deploy["spec"]["template"]["spec"]["containers"][0]
    names = [item.get("secretRef", {}).get("name")
             for item in container["envFrom"]]
    assert "toptiger-inference-secrets" in names
    assert service["spec"]["type"] == "ClusterIP"
    assert "readinessProbe" in container


def test_networkpolicy_and_hpa_are_separate():
    policy = documents("deploy/kubernetes/networkpolicy.yaml")[0]
    assert policy["kind"] == "NetworkPolicy"
    assert policy["spec"]["podSelector"]["matchLabels"]["app"] == "toptiger-vllm"
    hpa = documents("deploy/kubernetes/gateway-hpa.yaml")[0]
    assert hpa["spec"]["scaleTargetRef"]["name"] == "inference-gateway"


def test_scaledobject_is_opt_in_template():
    scale = documents("deploy/kubernetes/vllm-scaledobject.example.yaml")[0]
    assert scale["kind"] == "ScaledObject"
    assert scale["spec"]["minReplicaCount"] >= 1
    assert scale["spec"]["scaleTargetRef"]["name"] == "vllm"


def test_pose_model_is_mounted_read_only_on_worker_only():
    services = documents("docker-compose.pose.yml")[0]["services"]
    assert set(services) == {"worker"}
    worker = services["worker"]
    assert worker["build"]["target"] == "pose-worker"
    mount, = worker["volumes"]
    assert mount["type"] == "bind"
    assert mount["target"] == worker["environment"]["TOPTIGER_POSE_MODEL"]
    assert mount["read_only"] is True
    assert mount["bind"]["create_host_path"] is False
