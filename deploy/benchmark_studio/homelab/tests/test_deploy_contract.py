import ast
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[4]
DEPLOY = ROOT / "deploy/benchmark_studio/homelab"


class HomelabDeploymentContractTest(unittest.TestCase):
    def test_only_private_local_tagged_images_are_deployed(self) -> None:
        compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
        images = re.findall(r"^\s+image:\s+(\S+)", compose, re.MULTILINE)
        self.assertEqual(
            set(images),
            {
                "benchmark-studio-postgres:local",
                "benchmark-studio-clickhouse:local",
                "benchmark-studio-control:local",
                "benchmark-studio-ui:local",
                "benchmark-studio-gateway:local",
            },
        )
        self.assertNotIn("build:", compose)
        self.assertIn("internal: true", compose)
        self.assertIn("com.docker.network.bridge.enable_ip_masquerade: \"false\"", compose)
        self.assertIn("subnet: 172.29.87.0/29", compose)
        self.assertIn("com.docker.network.bridge.name: br-bench-prev", compose)
        self.assertIn(
            "./clickhouse-config/benchmark-preview-limits.xml:/etc/clickhouse-server/config.d/benchmark-preview-limits.xml:ro",
            compose,
        )
        self.assertIn("192.168.20.68:18900:8080", compose)
        self.assertIn("192.168.20.68:18901:8080", compose)
        self.assertNotIn("benchmark-studio-test_", compose)
        guard = (DEPLOY / "egress-guard.sh").read_text(encoding="utf-8")
        unit = (DEPLOY / "benchmark-studio-preview-egress.service").read_text(encoding="utf-8")
        self.assertIn("-s \"$subnet\" -j DROP", guard)
        self.assertIn("-j \"$policy_chain\"", guard)
        self.assertIn("chain=BENCH_PREV_EGRESS", guard)
        self.assertIn("host_chain=BENCH_PREV_HOST", guard)
        self.assertLessEqual(len("BENCH_PREV_EGRESS"), 28)
        self.assertLessEqual(len("BENCH_PREV_HOST"), 28)
        self.assertIn('ensure_policy_chain "$host_chain" INPUT', guard)
        self.assertIn("-s \"$subnet\" -j DROP", guard)
        self.assertIn("Before=docker.service", unit)
        self.assertIn("ReadWritePaths=/run", unit)
        api_service = compose.split("  control-api:", 1)[1].split("  gateway:", 1)[0]
        self.assertNotIn("ports:", api_service)
        self.assertIn("benchmark-source-not-configured.invalid", api_service)
        self.assertIn("CLICKHOUSE_SOURCE_USER: disabled", api_service)

    def test_preview_has_no_seed_data_and_blocks_benchmark_runs(self) -> None:
        init_sql = (DEPLOY / "clickhouse-init/01-sandbox.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertNotRegex(init_sql, r"\binsert\s+into\b|\bnumbers\s*\(")
        self.assertRegex(init_sql, r"create database(?: if not exists)? benchmark_sandbox")
        limits = (DEPLOY / "clickhouse-config/benchmark-preview-limits.xml").read_text(
            encoding="utf-8"
        )
        self.assertIn("<background_schedule_pool_size>32</background_schedule_pool_size>", limits)
        gateway = (DEPLOY / "gateway.conf").read_text(encoding="utf-8")
        self.assertRegex(gateway, r"location\s*=\s*/api/v1/runs")
        self.assertIn("return 503", gateway)
        self.assertIn("not available in this preview deployment", gateway)

    def test_frontend_uses_private_same_origin_api_and_release_is_checksummed(self) -> None:
        runtime = (DEPLOY / "runtime-config.js").read_text(encoding="utf-8")
        self.assertIn('apiBaseUrl: "https://benchmark.lan.awesomeio.ru"', runtime)
        for script in ("build-release.sh", "deploy-release.sh", "verify-release.sh", "rollback-release.sh"):
            self.assertTrue((DEPLOY / script).is_file(), script)
        for helper in ("configure-hosting.sh", "verify-release.sh"):
            self.assertTrue(os.access(DEPLOY / helper, os.X_OK), f"{helper} must be directly executable")
        build = (DEPLOY / "build-release.sh").read_text(encoding="utf-8")
        deploy = (DEPLOY / "deploy-release.sh").read_text(encoding="utf-8")
        verify = (DEPLOY / "verify-release.sh").read_text(encoding="utf-8")
        rollback = (DEPLOY / "rollback-release.sh").read_text(encoding="utf-8")
        configure = (DEPLOY / "configure-hosting.sh").read_text(encoding="utf-8")
        self.assertIn("DDL Benchmark Engine", configure)
        self.assertIn("DDL Benchmark Engine", verify)
        self.assertNotIn("DB Benchmark", configure + verify)
        self.assertIn("sha256sum", build)
        self.assertIn("--network=none", build)
        self.assertIn("sha256sum -c", deploy)
        self.assertIn("--pull never", deploy)
        self.assertIn("flock -n 9", deploy)
        stage_services = "up -d --no-build --pull never --wait --wait-timeout 180 postgres clickhouse ui"
        initialize_sandbox = "exec -T clickhouse clickhouse-client --multiquery"
        self.assertIn(stage_services, deploy)
        self.assertIn(initialize_sandbox, deploy)
        self.assertLess(deploy.index(stage_services), deploy.index(initialize_sandbox))
        self.assertLess(deploy.index(initialize_sandbox), deploy.rindex("up -d --no-build --pull never"))
        self.assertIn("configure-hosting.sh", deploy)
        self.assertIn("system.users WHERE name = 'benchmark_writer'", verify)
        self.assertIn("system.databases WHERE name = 'benchmark_sandbox'", verify)
        self.assertIn("docker port", verify)
        self.assertIn("BENCH_PREV_EGRESS", verify)
        self.assertIn('server_hostname="benchmark.lan.awesomeio.ru"', verify)
        self.assertIn("--privileged --network host", deploy)
        self.assertIn("os.chroot(sys.argv[1])", deploy)
        self.assertIn("os.execv(sys.argv[2], sys.argv[2:])", deploy)
        self.assertNotIn("down -v", deploy + rollback)

    def test_release_output_refuses_to_overwrite_existing_files(self) -> None:
        build = (DEPLOY / "build-release.sh").read_text(encoding="utf-8")
        self.assertIn("Output directory must be new or empty", build)
        self.assertIn("! -path '*/__pycache__/*'", build)

    def test_preview_readiness_checks_its_required_sandbox_not_an_external_source(self) -> None:
        api = ROOT / "apps/realtime_control_api/src/realtime_control_api/main.py"
        tree = ast.parse(api.read_text(encoding="utf-8"))
        ready_functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "ready"
        ]
        self.assertEqual(len(ready_functions), 1)
        calls = [
            node
            for node in ast.walk(ready_functions[0])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "clickhouse_query"
        ]
        self.assertTrue(
            any(
                any(
                    keyword.arg == "sandbox"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in call.keywords
                )
                for call in calls
            ),
            "Preview readiness must probe the isolated sandbox, not an unconfigured external source.",
        )


if __name__ == "__main__":
    unittest.main()
