"""Actual import closure plus a guarded real CLI driver, not a handwritten architecture graph."""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from tests.helpers.application import synthetic_environment
from tests.helpers.cli_fake import CliFakeHarness, _driver_code

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "hermes_mailcloud"
SDK_ROOTS = {"typer", "click", "rich", "PySide6", "PySide2", "PyQt6", "PyQt5", "tkinter", "mcp"}
CLI_ONLY = {"hermes_mailcloud.cli", "hermes_mailcloud.__main__"}
ORCHESTRATION = (
    "hermes_mailcloud.commands",
    "hermes_mailcloud.batch",
    "hermes_mailcloud.doctor",
    "hermes_mailcloud.rclone",
    "hermes_mailcloud.config",
    "hermes_mailcloud.core.policy",
)


def _imports(source: str, module: str, package_module: bool = False) -> set[str]:
    """Resolve real absolute/relative and literal dynamic imports, including lazy bodies."""
    tree = ast.parse(source)
    package = module if package_module else module.rpartition(".")[0]
    targets = set()
    namespaces, loaders = {"importlib"}, {"__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
                if alias.name == "importlib":
                    namespaces.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = (
                importlib.util.resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module or ""
            )
            targets.add(base)
            targets.update(base + "." + alias.name for alias in node.names if alias.name != "*")
            if node.module == "importlib" and node.level == 0:
                loaders.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "import_module"
                )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        dynamic = (
            isinstance(func, ast.Name)
            and func.id in loaders
            or isinstance(func, ast.Attribute)
            and func.attr == "import_module"
            and isinstance(func.value, ast.Name)
            and func.value.id in namespaces
        )
        if (
            dynamic
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            name = node.args[0].value
            selected_package = package
            if (
                len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                selected_package = node.args[1].value
            for keyword in node.keywords:
                if (
                    keyword.arg == "package"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    selected_package = keyword.value.value
            targets.add(
                importlib.util.resolve_name(name, selected_package)
                if name.startswith(".")
                else name
            )
    return targets


def _sdk_dependency(target: str) -> bool:
    return target.split(".")[0] in SDK_ROOTS or any(
        target == name or target.startswith(name + ".") for name in CLI_ONLY
    )


def _cli_writes(source: str) -> list[str]:
    """A driver may inject the composition port, never mutate CLI business attributes."""
    found = []
    for node in ast.walk(ast.parse(source)):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, (ast.AnnAssign, ast.AugAssign))
            else []
        )
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "cli"
            ):
                found.append(target.attr)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "cli"
        ):
            found.append("setattr")
    return found


@pytest.mark.parametrize(
    "source",
    [
        "import typer",
        "import hermes_mailcloud.cli as shell",
        "from .. import cli",
        "def later():\n    from ..cli import app",
        "def later():\n    import rich.console",
        "import importlib as loader\nloader.import_module('hermes_mailcloud.cli')",
        "from importlib import import_module as load\nload('click')",
        "import importlib\n"
        "importlib.import_module('..cli', package='hermes_mailcloud.application')",
        "__import__('mcp')",
    ],
)
def test_import_detector_rejects_absolute_relative_lazy_and_dynamic_sdk_routes(source) -> None:
    assert any(
        _sdk_dependency(name) for name in _imports(source, "hermes_mailcloud.application.service")
    )


def test_application_actual_transitive_import_closure_is_sdk_independent() -> None:
    sources = {}
    for path in PACKAGE.rglob("*.py"):
        parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
        is_package = parts[-1] == "__init__"
        module = ".".join(parts[:-1] if is_package else parts)
        sources[module] = (path, is_package)
    pending, visited, failures = ["hermes_mailcloud.application"], set(), []
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path, is_package = sources[module]
        for target in _imports(path.read_text(encoding="utf-8"), module, is_package):
            if _sdk_dependency(target):
                failures.append((module, target))
            parts = target.split(".")
            pending.extend(
                name
                for count in range(1, len(parts) + 1)
                if (name := ".".join(parts[:count])) in sources and name not in visited
            )
    assert {
        "hermes_mailcloud.application.service",
        "hermes_mailcloud.batch",
        "hermes_mailcloud.doctor",
        "hermes_mailcloud.rclone.install",
        "hermes_mailcloud.commands.public",
        "hermes_mailcloud.core.result",
    } <= visited
    assert failures == []


def test_cli_imports_only_presentation_and_application_contracts() -> None:
    imports = _imports((PACKAGE / "cli.py").read_text(encoding="utf-8"), "hermes_mailcloud.cli")
    assert not {
        target
        for target in imports
        if any(target == owner or target.startswith(owner + ".") for owner in ORCHESTRATION)
    }


def test_cli_has_no_remaining_legacy_execution_definitions() -> None:
    tree = ast.parse((PACKAGE / "cli.py").read_text(encoding="utf-8"))
    obsolete = {
        "_placeholder",
        "_run_rclone_command",
        "_run_doctor_command",
        "_run_batch_command",
        "_legacy_profile",
    }
    assert not {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (node.name in obsolete or node.name.startswith("_effective_"))
    }


@pytest.mark.parametrize("driver", ["source", "installed"])
def test_drivers_have_only_the_genuine_composition_injection(driver) -> None:
    source = (
        _driver_code(Path("external.py"))
        if driver == "source"
        else (ROOT / "tests/helpers/installed_fake_driver.py").read_text(encoding="utf-8")
    )
    assert _cli_writes(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "cli.RcloneRunner = replacement",
        "setattr(cli, 'BatchCommands', replacement)",
        "def later():\n    cli.resolve_config = replacement",
    ],
)
def test_driver_detector_rejects_lazy_and_attribute_legacy_mutation(source) -> None:
    assert _cli_writes(source)


def test_real_source_driver_executes_with_cli_business_mutation_forbidden(tmp_path: Path) -> None:
    harness = CliFakeHarness.create(tmp_path)
    harness.control.write_text(
        json.dumps(
            {
                "log": str(harness.calls),
                "responses": {
                    "lsjson": {
                        "stdout": json.dumps(
                            [{"Path": "zero.txt", "Name": "zero.txt", "Size": 0, "IsDir": False}]
                        )
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    environment = synthetic_environment(tmp_path)
    environment["HMC_RCLONE_PATH"] = str(harness.script)
    prelude = textwrap.dedent("""
        import types
        import hermes_mailcloud.cli as cli
        class PresentationOnly(types.ModuleType):
            def __setattr__(self, name, value):
                if name in {
                    'RcloneRunner', 'BatchCommands', 'DoctorCommands',
                    'resolve_config', 'prepare_rclone'
                }:
                    raise AssertionError('driver mutated CLI business seam')
                return super().__setattr__(name, value)
        cli.__class__ = PresentationOnly
    """)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            prelude + _driver_code(harness.script),
            "ls",
            "/TEST/owned",
            "--json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["result"]["items"] == [
        {"path": "/TEST/owned/zero.txt", "name": "zero.txt", "type": "file", "size": 0}
    ]
    assert harness.recorded_calls() == [["lsjson", "fake:/TEST/owned"]]
