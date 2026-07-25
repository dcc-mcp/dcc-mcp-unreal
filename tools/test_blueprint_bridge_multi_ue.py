"""Run Blueprint Bridge tests across all discovered Unreal Engine installations.

Usage:
    python tools/test_blueprint_bridge_multi_ue.py [--skip-runtime] [--json]

Installs dcc-mcp-unreal into each UE's Python, runs unit tests outside the editor,
and optionally runs runtime regression inside each UE Editor (UnrealEditor-Cmd.exe).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the discovery module
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
from discover_ue_versions import discover  # noqa: E402

# Template project to use for runtime tests
_TEMPLATE_PROJECT = None  # Will be resolved per UE version

# Test scripts
_UNIT_TESTS = [
    "tests/test_unreal_bridge_blueprint.py",
    "tests/test_blueprint_skills.py",
]
_RUNTIME_SCRIPT = "tests/blueprint_runtime_regression.py"

# Timeout for UE Editor startup + test execution
_UE_TIMEOUT_SECONDS = 300


def _find_template_project(ue_path: Path) -> Path | None:
    """Find a suitable .uproject template to use for testing."""
    templates_dir = ue_path / "Templates"
    if not templates_dir.is_dir():
        return None

    # Prefer a simple BP template
    preferred = [
        "TP_AEC_BlankBP",
        "TP_BlankBP",
        "TP_FirstPersonBP",
        "TP_ThirdPersonBP",
    ]
    for name in preferred:
        for tmpl_dir in templates_dir.iterdir():
            if tmpl_dir.is_dir() and name.lower() in tmpl_dir.name.lower():
                uproject = tmpl_dir / f"{tmpl_dir.name}.uproject"
                if uproject.is_file():
                    return uproject

    # Fallback: any .uproject
    for tmpl_dir in templates_dir.iterdir():
        if tmpl_dir.is_dir():
            for f in tmpl_dir.iterdir():
                if f.suffix == ".uproject":
                    return f

    return None


def _install_package(ue: dict, project_root: Path) -> dict:
    """Install dcc-mcp-unreal into the UE's Python environment."""
    python_exe = ue["python_exe"]
    name = ue["name"]

    result = {
        "ue_version": name,
        "step": "install",
        "success": False,
    }

    try:
        # Install package
        proc = subprocess.run(
            [python_exe, "-m", "pip", "install", "--force-reinstall", str(project_root)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(project_root),
        )
        if proc.returncode != 0:
            result["error"] = proc.stderr[-500:]
            return result

        # Install pytest if needed
        proc = subprocess.run(
            [python_exe, "-c", "import pytest"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            subprocess.run(
                [python_exe, "-m", "pip", "install", "pytest", "pyyaml"],
                capture_output=True,
                text=True,
                timeout=60,
            )

        result["success"] = True
    except subprocess.TimeoutExpired:
        result["error"] = "Installation timed out"
    except Exception as exc:
        result["error"] = str(exc)

    return result


def _run_unit_tests(ue: dict, project_root: Path) -> dict:
    """Run pytest unit tests using the UE's Python."""
    python_exe = ue["python_exe"]
    name = ue["name"]

    result = {
        "ue_version": name,
        "step": "unit_tests",
        "success": False,
        "passed": 0,
        "failed": 0,
        "total": 0,
    }

    try:
        test_paths = [str(project_root / t) for t in _UNIT_TESTS]
        proc = subprocess.run(
            [python_exe, "-m", "pytest", *test_paths, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(project_root),
        )
        result["stdout"] = proc.stdout[-3000:] if proc.stdout else ""
        result["stderr"] = proc.stderr[-1000:] if proc.stderr else ""
        result["success"] = proc.returncode == 0

        # Parse pytest summary
        for line in proc.stdout.splitlines():
            if "passed" in line and "=" in line:
                result["summary_line"] = line.strip()
                break
    except subprocess.TimeoutExpired:
        result["error"] = "Unit tests timed out"
    except Exception as exc:
        result["error"] = str(exc)

    return result


def _run_runtime_regression(ue: dict, project_root: Path) -> dict:
    """Run the runtime regression inside UE Editor."""
    cmd_exe = ue.get("cmd_exe")
    name = ue["name"]
    ue_path = Path(ue["path"])

    result = {
        "ue_version": name,
        "step": "runtime_regression",
        "success": False,
    }

    if not cmd_exe:
        result["error"] = "No UnrealEditor-Cmd.exe available"
        return result

    # Find a template project
    template = _find_template_project(ue_path)
    if not template:
        result["error"] = "No template project found"
        return result

    runtime_script = project_root / _RUNTIME_SCRIPT
    if not runtime_script.is_file():
        result["error"] = f"Runtime script not found: {runtime_script}"
        return result

    try:
        proc = subprocess.run(
            [
                cmd_exe,
                str(template),
                f"-ExecutePythonScript={runtime_script}",
                "-stdout",
                "-unattended",
                "-nullrhi",
                "-nosplash",
            ],
            capture_output=True,
            text=True,
            timeout=_UE_TIMEOUT_SECONDS,
            cwd=str(project_root),
        )

        # Check for result JSON
        result_json_path = runtime_script.with_suffix(".result.json")
        if result_json_path.is_file():
            try:
                runtime_result = json.loads(result_json_path.read_text(encoding="utf-8"))
                result["runtime_result"] = runtime_result
                result["success"] = runtime_result.get("all_passed", False)
                result["passed"] = runtime_result.get("passed", 0)
                result["failed"] = runtime_result.get("failed", 0)
                result["total"] = runtime_result.get("total", 0)
            except (json.JSONDecodeError, KeyError) as exc:
                result["error"] = f"Failed to parse result JSON: {exc}"
        else:
            # No JSON result = script likely crashed before writing
            # Check exit code and look for Python errors in output
            stderr_tail = proc.stderr[-500:] if proc.stderr else ""
            stdout_tail = proc.stdout[-500:] if proc.stdout else ""
            result["error"] = f"No result JSON. Exit code: {proc.returncode}. stderr tail: {stderr_tail[:300]}"

    except subprocess.TimeoutExpired:
        result["error"] = f"Runtime regression timed out after {_UE_TIMEOUT_SECONDS}s"
    except Exception as exc:
        result["error"] = str(exc)

    return result


def run_all(skip_runtime: bool = False) -> dict:
    """Run the full test matrix across all UE versions."""
    all_ue = discover()
    testable = [ue for ue in all_ue if ue["testable"]]

    if not testable:
        return {"error": "No testable UE installations found", "results": []}

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ue_count": len(testable),
        "ue_versions": [ue["name"] for ue in testable],
        "skip_runtime": skip_runtime,
        "results": [],
        "summary": {"total": 0, "passed_unit": 0, "passed_runtime": 0, "failed": 0},
    }

    for ue in testable:
        name = ue["name"]
        print(f"\n{'='*60}")
        print(f"  Testing: {name} (v{ue['precise_version']})")
        print(f"  Path:    {ue['path']}")
        print(f"  Python:  {ue['python_exe']}")
        print(f"{'='*60}")

        ue_result: dict[str, Any] = {"ue_version": name, "precise_version": ue["precise_version"], "steps": []}

        # Step 1: Install
        print(f"  [1/3] Installing dcc-mcp-unreal...")
        install = _install_package(ue, _PROJECT_ROOT)
        ue_result["steps"].append(install)
        if not install["success"]:
            print(f"        ❌ Install failed: {install.get('error', 'unknown')}")
            ue_result["overall"] = "failed"
            report["results"].append(ue_result)
            report["summary"]["failed"] += 1
            report["summary"]["total"] += 1
            continue
        print(f"        ✅ Installed")

        # Step 2: Unit tests
        print(f"  [2/3] Running unit tests...")
        unit = _run_unit_tests(ue, _PROJECT_ROOT)
        ue_result["steps"].append(unit)
        if unit["success"]:
            print(f"        ✅ Unit tests passed")
            report["summary"]["passed_unit"] += 1
        else:
            print(f"        ❌ Unit tests failed: {unit.get('error', unit.get('summary_line', 'unknown'))}")
        report["summary"]["total"] += 1

        # Step 3: Runtime regression (optional)
        if not skip_runtime:
            print(f"  [3/3] Running runtime regression (this may take a few minutes)...")
            start = time.time()
            runtime = _run_runtime_regression(ue, _PROJECT_ROOT)
            elapsed = time.time() - start
            ue_result["steps"].append(runtime)
            if runtime["success"]:
                print(f"        ✅ Runtime regression passed ({elapsed:.0f}s)")
                report["summary"]["passed_runtime"] += 1
            else:
                print(f"        ❌ Runtime regression failed ({elapsed:.0f}s): {runtime.get('error', '')[:200]}")
            # Also check individual tests
            rr = runtime.get("runtime_result", {})
            if rr:
                p = rr.get("passed", 0)
                f = rr.get("failed", 0)
                print(f"        Tests: {p} passed, {f} failed, {rr.get('total', 0)} total")

        ue_result["overall"] = "passed" if all(s.get("success", False) for s in ue_result["steps"]) else "failed"
        report["results"].append(ue_result)

    return report


def main() -> None:
    skip_runtime = "--skip-runtime" in sys.argv
    output_json = "--json" in sys.argv

    print("=" * 60)
    print("  DCC MCP Unreal — Blueprint Bridge Multi-UE Test Runner")
    print("=" * 60)

    report = run_all(skip_runtime=skip_runtime)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    s = report["summary"]
    print(f"  UE versions tested: {report['ue_count']}")
    print(f"  Unit tests passed:  {s['passed_unit']}/{s['total']}")
    if not skip_runtime:
        print(f"  Runtime passed:     {s['passed_runtime']}/{s['total']}")

    for r in report["results"]:
        status = "✅" if r.get("overall") == "passed" else "❌"
        print(f"  {status} {r['ue_version']:10s} (v{r['precise_version']}): {r['overall']}")

    # Write JSON report
    report_path = _PROJECT_ROOT / "tools" / "multi_ue_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n  Full report: {report_path}")

    if output_json:
        print(json.dumps(report, indent=2, default=str))

    # Exit with non-zero if any failed
    failed = any(r.get("overall") != "passed" for r in report["results"])
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
