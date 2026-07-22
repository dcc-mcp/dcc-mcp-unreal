"""PyOxidizer configuration for the standalone Unreal sidecar launcher."""

def make_exe():
    dist = default_python_distribution()
    policy = dist.make_python_packaging_policy()
    policy.resources_location = "filesystem-relative:lib"

    python_config = dist.make_python_interpreter_config()
    python_config.oxidized_importer = False
    python_config.filesystem_importer = True
    python_config.module_search_paths = ["$ORIGIN/lib"]
    python_config.run_module = "dcc_mcp_unreal._standalone_entry"
    python_config.parse_argv = False

    exe = dist.to_python_executable(
        name="dcc-mcp-unreal",
        packaging_policy=policy,
        config=python_config,
    )
    exe.add_python_resources(exe.pip_install(["--no-deps", "."]))
    return exe

def make_install(exe):
    files = FileManifest()
    files.add_python_resource(".", exe)
    return files

register_target("exe", make_exe)
register_target("install", make_install, depends=["exe"], default=True)
resolve_targets()
