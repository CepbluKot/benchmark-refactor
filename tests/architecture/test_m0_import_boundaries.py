import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GREENFIELD_ROOTS = (
    ROOT / "packages",
    ROOT / "adapters",
    ROOT / "apps" / "m0_control_plane",
    ROOT / "plugins" / "toy",
)


def _python_files(root: Path):
    yield from (
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and "migrations/versions" not in str(path)
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_greenfield_never_imports_legacy_or_celery() -> None:
    forbidden = {"src", "main", "settings", "celery", "redis"}
    violations: list[str] = []
    for root in GREENFIELD_ROOTS:
        for path in _python_files(root):
            for module in _imports(path):
                if module.split(".", 1)[0] in forbidden:
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_domain_uses_only_standard_library_and_itself() -> None:
    domain = ROOT / "packages" / "experiment_domain" / "src" / "experiment_domain"
    allowed = {"__future__", "dataclasses", "datetime", "enum", "experiment_domain"}
    violations: list[str] = []
    for path in _python_files(domain):
        for module in _imports(path):
            if module.split(".", 1)[0] not in allowed:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_core_workflows_do_not_import_backend_or_persistence() -> None:
    core = ROOT / "packages" / "core_workflows" / "src" / "core_workflows"
    forbidden = {"plugin_toy_m0", "benchmark_adapters", "sqlalchemy", "psycopg"}
    violations: list[str] = []
    for path in _python_files(core):
        for module in _imports(path):
            if module.split(".", 1)[0] in forbidden:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_durable_workflows_do_not_import_nondeterministic_io_apis() -> None:
    core = ROOT / "packages" / "core_workflows" / "src" / "core_workflows"
    forbidden = {
        "asyncio",
        "grpc",
        "httpx",
        "os",
        "pathlib",
        "random",
        "requests",
        "secrets",
        "socket",
        "subprocess",
        "time",
        "urllib",
        "uuid",
    }
    violations: list[str] = []
    for path in _python_files(core):
        for module in _imports(path):
            if module.split(".", 1)[0] in forbidden:
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    assert violations == []


def test_toy_plugin_distribution_has_no_product_database_dependency() -> None:
    pyproject = (
        (ROOT / "plugins" / "toy" / "pyproject.toml")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "sqlalchemy" not in pyproject
    assert "psycopg" not in pyproject
    assert "benchmark-postgres-adapter" not in pyproject
