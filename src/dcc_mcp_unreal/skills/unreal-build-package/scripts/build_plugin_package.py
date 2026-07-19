"""Build an installable DCC MCP Unreal plugin archive."""

from __future__ import annotations

from _build_package import build_plugin_package_impl
from dcc_mcp_core.skills_helper import run_main, skill_entry


@skill_entry
def build_plugin_package(
    repository_root: str,
    ue_root: str,
    mode: str = "native",
    python_executable: str = "",
    core_wheel: str = "",
    core_spec: str = "dcc-mcp-core>=0.19.45,<1.0.0",
    vctoolchain_version: str = "",
    **kwargs,
) -> dict:
    return build_plugin_package_impl(
        repository_root=repository_root,
        ue_root=ue_root,
        mode=mode,
        python_executable=python_executable,
        core_wheel=core_wheel,
        core_spec=core_spec,
        vctoolchain_version=vctoolchain_version,
    )


def main(**kwargs) -> dict:
    return build_plugin_package(**kwargs)


if __name__ == "__main__":
    run_main(main)
