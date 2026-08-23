import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "hatchet_spike" / "compose.yaml"
REQUIRED_ENV = {
    "M0_POSTGRES_SUPERUSER_PASSWORD": "test-superuser",
    "M0_HATCHET_DATABASE_PASSWORD": "test-hatchet",
    "M0_PRODUCT_MIGRATOR_PASSWORD": "test-migrator",
    "M0_PRODUCT_APP_PASSWORD": "test-app",
    "M0_HATCHET_ADMIN_EMAIL": "admin@example.invalid",
    "M0_HATCHET_ADMIN_PASSWORD": "test-admin",
}


def _compose_config() -> dict[str, object]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not installed")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "operator-ui",
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env={**os.environ, **REQUIRED_ENV},
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_every_compose_service_has_the_hard_resource_envelope() -> None:
    config = _compose_config()
    services = config["services"]
    assert services
    for name, service in services.items():
        assert service["cpus"] <= 1, name
        assert int(service["mem_limit"]) <= 1024 * 1024 * 1024, name


def test_external_runtime_images_are_digest_pinned() -> None:
    config = _compose_config()
    for name, service in config["services"].items():
        image = service["image"]
        if image.startswith("benchmark-m0-"):
            continue
        assert "@sha256:" in image, f"{name}: {image}"

    for dockerfile in (
        ROOT / "deploy" / "hatchet_spike" / "Dockerfile.control",
        ROOT / "deploy" / "hatchet_spike" / "Dockerfile.toy-plugin",
    ):
        text = dockerfile.read_text(encoding="utf-8")
        assert "python:3.12-alpine@sha256:" in text


def test_hatchet_uses_postgres_transport_and_plugin_has_no_product_db() -> None:
    config = _compose_config()
    services = config["services"]
    for name in ("hatchet-api", "hatchet-engine"):
        environment = services[name]["environment"]
        assert environment["SERVER_MSGQUEUE_KIND"] == "postgres"
        assert environment["SERVER_MSGQUEUE_PUBSUB_KIND"] == "postgres"
        assert environment["SERVER_SECURITY_CHECK_ENABLED"] == "false"
        assert environment["SERVER_ANALYTICS_POSTHOG_ENABLED"] == "false"

    plugin_environment = services["toy-worker"]["environment"]
    assert "PRODUCT_DATABASE_URL" not in plugin_environment
    internal_networks = {
        name
        for name, network in config["networks"].items()
        if network.get("internal") is True
    }
    assert {
        "core-api",
        "hatchet-db",
        "operator-ui",
        "plugin-api",
        "product-db",
        "worker-bus",
    } <= internal_networks

    plugin_networks = set(services["toy-worker"]["networks"])
    finalization_networks = set(services["finalization-api"]["networks"])
    assert plugin_networks.isdisjoint(finalization_networks)


def test_worker_token_is_stable_across_partial_compose_up() -> None:
    config = _compose_config()
    command = "\n".join(config["services"]["worker-token"]["command"])
    assert "if [ ! -s /run/hatchet-token/token ]" in command
    assert "token.tmp" in command


def test_database_connect_privileges_are_split_on_fresh_bootstrap() -> None:
    script = (ROOT / "deploy" / "hatchet_spike" / "init-postgres.sh").read_text(
        encoding="utf-8"
    )
    assert "REVOKE CONNECT, TEMPORARY ON DATABASE hatchet FROM PUBLIC" in script
    assert (
        "REVOKE CONNECT, TEMPORARY ON DATABASE benchmark_control FROM PUBLIC" in script
    )
    assert "GRANT CONNECT, TEMPORARY ON DATABASE hatchet TO hatchet" in script
    assert (
        "GRANT CONNECT ON DATABASE benchmark_control TO benchmark_migrator, "
        "benchmark_app"
    ) in script
