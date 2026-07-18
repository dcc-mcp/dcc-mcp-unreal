set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
set quiet

ue_version := env_var_or_default("UE_VERSION", "5.7")
ue_root := env_var_or_default("UE_ROOT", "C:\\Program Files\\Epic Games\\UE_" + ue_version)
core_root := env_var_or_default("DCC_MCP_CORE_ROOT", "..\\dcc-mcp-core")
core_wheel := env_var_or_default("DCC_MCP_CORE_WHEEL", "")
core_wheel_url := env_var_or_default("DCC_MCP_CORE_WHEEL_URL", "")
package_mode := env_var_or_default("DCC_MCP_UNREAL_PACKAGE_MODE", "native")
python_plugin_name := env_var_or_default("DCC_MCP_UNREAL_PYTHON_PLUGIN", "PythonScriptPlugin")

default:
    just --list

# Show the Unreal/toolchain paths that packaging will use.
doctor:
    & { $ue = '{{ue_root}}'; Write-Host "UE_ROOT=$ue"; Write-Host "PACKAGE_MODE={{package_mode}}"; Write-Host "PYTHON_PLUGIN={{python_plugin_name}}"; if (!(Test-Path -LiteralPath $ue)) { throw "UE_ROOT does not exist: $ue" }; $uat = Join-Path $ue 'Engine\Build\BatchFiles\RunUAT.bat'; if (Test-Path -LiteralPath $uat) { Write-Host "RunUAT=$uat" } else { Write-Warning "RunUAT.bat not found. Native precompiled builds need RunUAT." }; $py = Join-Path $ue 'Engine\Binaries\ThirdParty\Python3\Win64\python.exe'; if (Test-Path -LiteralPath $py) { Write-Host "UE Python=$py" } else { Write-Warning "UE bundled Python not found. Packaging will use the current Python unless --python is passed." }; $pythonPlugin = Join-Path $ue 'Engine\Plugins\Experimental\PythonScriptPlugin\PythonScriptPlugin.uplugin'; if (Test-Path -LiteralPath $pythonPlugin) { Write-Host "PythonScriptPlugin=$pythonPlugin" } else { Write-Warning "PythonScriptPlugin not found at the stock path. For internal forks set DCC_MCP_UNREAL_PYTHON_PLUGIN or use python-only/source mode." } }

lint:
    python tools/lint_skills.py
    python -m ruff check .

test:
    python -m pytest

validate-skills:
    python tools/lint_skills.py
    python -c "import dcc_mcp_core, pathlib; [print(path, dcc_mcp_core.validate_skill(str(path))) for path in pathlib.Path('src/dcc_mcp_unreal/skills').iterdir() if path.is_dir()]"

check: lint test validate-skills

# Download a dcc-mcp-core wheel release asset into dist/core-wheel/.
download-core-wheel release="latest" repo="dcc-mcp/dcc-mcp-core":
    & { $dir = Resolve-Path -LiteralPath .; $target = Join-Path $dir 'dist\core-wheel'; if ((Test-Path -LiteralPath $target) -and -not ((Resolve-Path -LiteralPath $target).Path.StartsWith($dir.Path))) { throw "Refusing to clean outside repo: $target" }; Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force -Path $target | Out-Null; if ('{{release}}' -eq 'latest') { gh release download --repo '{{repo}}' --pattern 'dcc_mcp_core-*.whl' --dir $target --clobber } else { gh release download '{{release}}' --repo '{{repo}}' --pattern 'dcc_mcp_core-*.whl' --dir $target --clobber }; Get-ChildItem -LiteralPath $target -Filter '*.whl' }

# Build the distributable uplugin zip. Set DCC_MCP_CORE_WHEEL or DCC_MCP_CORE_WHEEL_URL to avoid source builds.
uplugin:
    & { $cmd = @('packaging/build_distributable.py', '--ue-root', '{{ue_root}}', '--mode', '{{package_mode}}', '--python-plugin-name', '{{python_plugin_name}}'); if ('{{core_wheel}}') { $cmd += @('--core-wheel', '{{core_wheel}}') }; if ('{{core_wheel_url}}') { $cmd += @('--core-wheel-url', '{{core_wheel_url}}') }; python @cmd }

uplugin-wheel core_wheel:
    python packaging/build_distributable.py --ue-root '{{ue_root}}' --core-wheel '{{core_wheel}}' --mode '{{package_mode}}' --python-plugin-name '{{python_plugin_name}}'

uplugin-url url:
    python packaging/build_distributable.py --ue-root '{{ue_root}}' --core-wheel-url '{{url}}' --mode '{{package_mode}}' --python-plugin-name '{{python_plugin_name}}'

# Build a source-bearing plugin package with vendored Python payload, without UAT precompile.
uplugin-source:
    & { $cmd = @('packaging/build_distributable.py', '--ue-root', '{{ue_root}}', '--mode', 'source', '--python-plugin-name', '{{python_plugin_name}}'); if ('{{core_wheel}}') { $cmd += @('--core-wheel', '{{core_wheel}}') }; if ('{{core_wheel_url}}') { $cmd += @('--core-wheel-url', '{{core_wheel_url}}') }; python @cmd }

# Build a Python-only package for legacy/internal engines that provide their own Python bridge.
uplugin-python-only:
    & { $cmd = @('packaging/build_distributable.py', '--ue-root', '{{ue_root}}', '--mode', 'python-only', '--python-plugin-name', '{{python_plugin_name}}'); if ('{{core_wheel}}') { $cmd += @('--core-wheel', '{{core_wheel}}') }; if ('{{core_wheel_url}}') { $cmd += @('--core-wheel-url', '{{core_wheel_url}}') }; python @cmd }

# Backwards-compatible aliases.
package: uplugin

package-source:
    python packaging/build_plugin.py --ue-root '{{ue_root}}' --clean --zip

package-local-core:
    python packaging/build_plugin.py --ue-root '{{ue_root}}' --core-root '{{core_root}}' --use-local-core --clean --zip

package-fast:
    python packaging/build_plugin.py --ue-root '{{ue_root}}' --clean --zip --skip-python-deps

install-engine:
    & { $src = Resolve-Path -LiteralPath 'dist\package\DccMcpUnreal' -ErrorAction Stop; $ue = Resolve-Path -LiteralPath '{{ue_root}}' -ErrorAction Stop; $plugins = Join-Path $ue 'Engine\Plugins'; $dest = Join-Path $plugins 'DccMcpUnreal'; if ((Test-Path -LiteralPath $dest) -and -not ((Resolve-Path -LiteralPath $dest).Path.StartsWith($plugins))) { throw "Refusing to replace outside Engine\Plugins: $dest" }; Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item -LiteralPath $src -Destination $dest -Recurse; Write-Host "Installed $dest" }

install-project project:
    & { $src = Resolve-Path -LiteralPath 'dist\package\DccMcpUnreal' -ErrorAction Stop; $root = Resolve-Path -LiteralPath '{{project}}' -ErrorAction Stop; if ($root.Path.EndsWith('.uproject')) { $root = $root.ProviderPath | Split-Path | Resolve-Path }; $plugins = Join-Path $root 'Plugins'; $dest = Join-Path $plugins 'DccMcpUnreal'; New-Item -ItemType Directory -Force -Path $plugins | Out-Null; if ((Test-Path -LiteralPath $dest) -and -not ((Resolve-Path -LiteralPath $dest).Path.StartsWith($plugins))) { throw "Refusing to replace outside project Plugins: $dest" }; Remove-Item -LiteralPath $dest -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item -LiteralPath $src -Destination $dest -Recurse; Write-Host "Installed $dest" }

deploy-engine: install-engine

deploy project:
    just install-project '{{project}}'

ue-smoke project=".":
    just install-project '{{project}}'
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/run_ue_smoke.ps1 -Project '{{project}}' -UERoot '{{ue_root}}' -Mode native

ue-smoke-python project=".":
    just install-project '{{project}}'
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/run_ue_smoke.ps1 -Project '{{project}}' -UERoot '{{ue_root}}' -Mode python
