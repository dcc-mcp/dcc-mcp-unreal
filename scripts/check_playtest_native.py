"""Run exact production key/navigation/ticker bodies against behavioral API doubles.

This is a compiler-backed contract regression gate, not an Unreal build or live
host acceptance. Run with a fresh --output-dir; all compile/run evidence is kept.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unreal/plugin/Source/DccMcpUnreal/Private/DccMcpAutomationLibrary.cpp"


def extract_bodies(text):
    spans = []

    def extract(start, end=None):
        pos = text.index(start)
        if end:
            stop = text.index(end, pos)
        else:
            stop = text.index("{", pos) + 1
            depth = 1
            while depth:
                depth += (text[stop] == "{") - (text[stop] == "}")
                stop += 1
        body = text[pos:stop]
        spans.append(dict(start=start, sha256=hashlib.sha256(body.encode()).hexdigest()))
        return body

    bodies = [
        extract("#if ENGINE_MAJOR_VERSION >= 5\nusing FDccMcpCoreTicker", "UClass* ResolveFabApiClass"),
        extract("bool IsPlayableWorld("),
        extract("TArray<FVector> FindNavigationWaypoints("),
        extract("bool StartPieInputSteeringInternal("),
    ]
    for name in ("AcquirePieKey", "PressOwnedPieKey", "ReleaseOwnedPieKey"):
        bodies.append(
            extract(("FString" if name == "AcquirePieKey" else "bool") + " UDccMcpAutomationLibrary::" + name + "(")
        )
    for start in (
        "static bool IsOwnedPieNavigationContext(",
        "static bool IsBoundedPieLocation(",
        "bool UDccMcpAutomationLibrary::NavigateOwnedPieToLocation(",
        "bool UDccMcpAutomationLibrary::NavigateOwnedPieToActor(",
        "bool UDccMcpAutomationLibrary::StartOwnedPieInputSteeringToLocation(",
        "bool UDccMcpAutomationLibrary::StopOwnedPieNavigation(",
    ):
        bodies.append(extract(start))
    return "\n\n".join(bodies), spans


def compiler_command(generated, executable, major, minor):
    if os.name != "nt":
        compiler = shutil.which("c++")
        if not compiler:
            raise RuntimeError("A C++17 compiler is required")
        return [
            compiler,
            "-std=c++17",
            f"-DENGINE_MAJOR_VERSION={major}",
            f"-DENGINE_MINOR_VERSION={minor}",
            str(generated),
            "-o",
            str(executable),
        ]
    installations = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft Visual Studio"
    candidates = sorted(installations.glob("*/*/VC/Auxiliary/Build/vcvars64.bat"))
    if not candidates:
        raise RuntimeError("Visual Studio C++ build tools are required")
    command = (
        f'"{candidates[-1]}" >nul && cl.exe /nologo /std:c++17 /EHsc /W3 '
        f"/DENGINE_MAJOR_VERSION={major} /DENGINE_MINOR_VERSION={minor} "
        f'"{generated}" /Fe:"{executable}" /Fo:"{executable.with_suffix(".obj")}"'
    )
    return 'cmd.exe /d /s /c "' + command + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bodies, spans = extract_bodies(SOURCE.read_text(encoding="utf-8"))
    for name in ("native_shim.hpp", "native_cases.cpp"):
        shutil.copyfile(ROOT / "tests/native" / name, output / name)
    generated = output / "native_extracted.cpp"
    generated.write_text('#include "native_shim.hpp"\n' + bodies + '\n#include "native_cases.cpp"\n', encoding="utf-8")
    (output / "extraction.json").write_text(
        json.dumps(
            dict(source=str(SOURCE), sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(), spans=spans), indent=2
        ),
        encoding="utf-8",
    )
    failed = False
    for major, minor in ((4, 18), (4, 26), (5, 5), (5, 7), (5, 8)):
        executable = output / f"native-{major}-{minor}.exe"
        command = compiler_command(generated, executable, major, minor)
        compiled = subprocess.run(command, cwd=output, capture_output=True, text=True, errors="replace", check=False)
        ran = (
            subprocess.run([str(executable)], cwd=output, capture_output=True, text=True, check=False)
            if compiled.returncode == 0
            else None
        )
        record = dict(
            version=f"{major}.{minor}",
            command=command,
            compile_exit=compiled.returncode,
            compile_stdout=compiled.stdout,
            compile_stderr=compiled.stderr,
            run_exit=ran.returncode if ran else None,
            run_stdout=ran.stdout if ran else None,
            run_stderr=ran.stderr if ran else None,
        )
        (output / f"result-{major}-{minor}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(record["version"], record["compile_exit"], record["run_exit"], flush=True)
        print(ran.stdout if ran else compiled.stdout + compiled.stderr, flush=True)
        failed |= compiled.returncode != 0 or ran is None or ran.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
