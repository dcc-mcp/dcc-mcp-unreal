"""Wrap an existing Windows game directory in an installer."""

from __future__ import annotations

from _build_package import package_prebuilt_windows_installer_impl
from dcc_mcp_core.skill import skill_entry


@skill_entry
def package_prebuilt_windows_installer(
    source_directory: str,
    executable_relative_path: str,
    output_directory: str,
    product_name: str = "",
    product_version: str = "1.0.0",
    publisher: str = "",
    installer_compiler_path: str = "",
    vc_redist_path: str = "",
    **kwargs,
) -> dict:
    return package_prebuilt_windows_installer_impl(
        source_directory=source_directory,
        executable_relative_path=executable_relative_path,
        output_directory=output_directory,
        product_name=product_name,
        product_version=product_version,
        publisher=publisher,
        installer_compiler_path=installer_compiler_path,
        vc_redist_path=vc_redist_path,
    )
