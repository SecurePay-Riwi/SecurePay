"""The engine's Kubernetes manifests (HU-58) run the same engine as ECS
and Compose: same command, port, health check, size and variables. The
CI also renders both overlays with `kubectl kustomize` (job terraform);
here kubectl is used when it is installed, and the files are read as YAML
otherwise."""

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[3]
K8S = ROOT / "infra" / "k8s"
OVERLAYS = ("kind", "eks")


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def compose_engine() -> dict:
    return load(ROOT / "docker-compose.yml")["services"]["decision-engine"]


def engine_container() -> dict:
    deployment = load(K8S / "base" / "deployment.yaml")
    return deployment["spec"]["template"]["spec"]["containers"][0]


def test_the_command_and_port_are_the_engine_s():
    container = engine_container()

    assert container["command"] == compose_engine()["command"]
    assert container["ports"][0]["containerPort"] == 8000
    for probe in ("readinessProbe", "livenessProbe"):
        assert container[probe]["httpGet"]["path"] == "/health"


def test_a_pod_is_the_size_of_an_ecs_task():
    variables = (ROOT / "infra/terraform/modules/ecs/variables.tf").read_text()
    cpu = re.search(r'variable "engine_cpu".*?default\s*=\s*(\d+)', variables, re.S)
    memory = re.search(
        r'variable "engine_memory".*?default\s*=\s*(\d+)', variables, re.S
    )
    requests = engine_container()["resources"]["requests"]

    assert requests["cpu"] == f"{int(cpu.group(1)) * 1000 // 1024}m"
    assert requests["memory"] == f"{int(memory.group(1)) // 1024}Gi"


def test_the_config_has_every_variable_of_compose():
    """Every engine variable of Compose, except LocalStack's endpoint and
    fake credentials, which only the kind overlay adds."""
    local_only = {"AWS_ENDPOINT_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
    config = load(K8S / "base" / "configmap.yaml")["data"]

    assert set(config) == set(compose_engine()["environment"]) - local_only
    assert all(isinstance(value, str) for value in config.values())


def test_each_overlay_names_files_that_exist():
    for overlay in OVERLAYS:
        folder = K8S / "overlays" / overlay
        kustomization = load(folder / "kustomization.yaml")
        files = kustomization.get("resources", []) + [
            patch["path"] for patch in kustomization.get("patches", [])
        ]
        for name in files:
            assert (folder / name).exists(), f"{overlay}: {name}"


def test_kind_publishes_the_node_port_on_8080():
    cluster = load(K8S / "overlays" / "kind" / "kind.yaml")
    service = load(K8S / "overlays" / "kind" / "service.yaml")
    mapping = cluster["nodes"][0]["extraPortMappings"][0]

    assert mapping["containerPort"] == service["spec"]["ports"][0]["nodePort"]
    assert mapping["hostPort"] == 8080
    assert len([n for n in cluster["nodes"] if n["role"] == "worker"]) == 2


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
@pytest.mark.parametrize("overlay", OVERLAYS)
def test_the_overlay_renders(overlay):
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(K8S / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    kinds = {doc["kind"] for doc in yaml.safe_load_all(rendered) if doc}

    assert {"Namespace", "ConfigMap", "Deployment", "Service"} <= kinds
    assert all(
        doc["metadata"].get("namespace") == "securepay"
        for doc in yaml.safe_load_all(rendered)
        if doc and doc["kind"] != "Namespace"
    )


def test_the_latency_script_uses_the_nearest_rank_percentile():
    spec = importlib.util.spec_from_file_location("latency", K8S / "latency.py")
    latency = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(latency)
    values = [float(n) for n in range(1, 101)]

    assert latency.percentile(values, 0.50) == 50
    assert latency.percentile(values, 0.99) == 99
    assert latency.percentile([7.0], 0.99) == 7
    assert latency.percentile([], 0.5) == 0
