# Native plugin wheel and receipt installer

`packaging/build_distributable.py --mode native` builds a Win64 plugin ZIP and
a normal platform adapter wheel. The wheel is the input to the receipt
installer. A plugin ZIP alone is not an installer input. Source and python-only
modes retain their existing behavior and do not produce a native wheel.

```powershell
python packaging/build_distributable.py --mode native --ue-root F:/UE/UE_5.7 `
  --python <build-python.exe> --core-wheel <pinned-core-wheel.whl> `
  --max-parallel-actions 2
```

Use an approved shared UAT/UBT time slot for native builds. The optional positive
integer `--max-parallel-actions` passes `-MaxParallelActions=N` to UBT through
normal UAT arguments. Omission keeps engine concurrency behavior. It does not
write this limit to a global toolchain configuration.

Native mode locks the canonical adapter source, plugin source and wheel
metadata before UAT. It requires a source plugin without `Binaries/`,
`Intermediate/`, `python/`, or an already packaged `src/dcc_mcp_unreal/_plugin`.
Do not feed a previous package or final build output back into the source tree.
UAT writes a fresh package under the cleaned work directory. The script checks
its source files, nonempty editor DLL, module mapping and selected engine
BuildId, and rechecks source and native output after packaging.
`pyproject.toml` and `README.md` are required metadata. `LICENSE` is optional,
matching ordinary repository wheel builds; its contents are locked when present,
and creating it after an absent-file source lock is rejected as source drift.

The finite payload layers are:

1. **Bootstrap runtime**: ordinary pip installs the canonical adapter source
   and selected Core into `work/payload/DccMcpUnreal/python`. That adapter's
   `_plugin` is the canonical source plugin and has no vendored Python runtime.
2. **Installer wheel payload**: the complete new UAT tree plus bootstrap runtime
   is staged at `work/wheel-payload/DccMcpUnreal`. A disposable source stage uses
   the repository's normal Hatch backend and `pip wheel`. A job-local standard
   Hatch build hook assigns `py3-none-win_amd64` and non-purelib metadata. The
   repository's default pyproject and version are unchanged. Hatch generates
   RECORD; the script checks every member's hash and exact `_plugin` equality.
3. **Final plugin ZIP runtime**: normal pip vendoring consumes that exact new
   adapter wheel through `build_plugin.py --adapter-wheel`. The final adapter's
   `_plugin` equals layer 2. The final Core package must equal the bootstrap
   Core package. The top-level plugin retains every new UAT file. No final
   package is used as wheel source, so the nesting stops at the source plugin
   in layer 1.

For UE4, existing native sidecar mode still omits incompatible embedded Python
dependencies. `--skip-core` explicitly omits Core and cannot establish a complete
embedded host runtime. Use a pinned Core wheel for a reproducible UE5 bundle.

With default output paths, the script exports:

- `dist/package/DccMcpUnreal/`: the complete plugin tree;
- `dist/DccMcpUnreal-<version>-<engine>-win64.zip`: plugin ZIP;
- `dist/package/native-wheels/dcc_mcp_unreal-<version>-py3-none-win_amd64.whl`:
  the independently pip-installable native adapter wheel;
- `dist/package/native-wheel-build.json`: source lock, complete UAT file
  hashes, BuildId, DLL hash, exported wheel path/hash and explicit Core wheel
  path/hash when supplied.

Install the exported native adapter wheel and its pinned Core wheel into an
independent interpreter using normal pip. Run the installer from that installed
distribution, with the same interpreter selected by `--python`:

```powershell
& <private-python.exe> -m pip install --no-deps <core-wheel.whl> <native-adapter-wheel.whl>
& <private-python.exe> -m dcc_mcp_unreal.install_cli install `
  --project <project.uproject> --dcc-path <ue-root> --python <private-python.exe>
```

The installer binds the installed adapter's `_plugin` and validates its normal
wheel RECORD before its ownership transaction. No DLL overlay, RECORD rewrite,
editable source import or unmanaged plugin adoption is required. Building and
static wheel verification do not establish native load, startup, UI, game
behavior, or project receipt acceptance; those remain separate checks.
