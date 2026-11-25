"""Small Hyper3D Rodin client used by the Unreal Canvas skill."""

from __future__ import annotations

import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple
from urllib.parse import urlparse

from dcc_mcp_core.skills_helper import atomic_write_bytes, http_request

DEFAULT_BASE_URL = "https://api.hyper3d.com/api/v2"
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
GEOMETRY_EXTENSIONS = (".glb", ".fbx", ".obj", ".usdz", ".stl")


class Hyper3DClientError(RuntimeError):
    """An error safe to return through an MCP result."""

    def __init__(self, message: str, code: str = "hyper3d_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _base_url() -> str:
    configured = os.environ.get("RODIN_API_BASE_URL", DEFAULT_BASE_URL).strip()
    parsed = urlparse(configured)
    if parsed.scheme == "https" and parsed.netloc:
        return configured.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return configured.rstrip("/")
    raise Hyper3DClientError(
        "RODIN_API_BASE_URL must use HTTPS, or HTTP on a loopback host",
        "invalid_api_base_url",
    )


def _api_url(path: str) -> str:
    return f"{_base_url()}/{path.lstrip('/')}"


def _api_key() -> str:
    key = (
        os.environ.get("HYPER3D_API_KEY", "").strip()
        or os.environ.get("RODIN_API_KEY", "").strip()
    )
    if not key:
        raise Hyper3DClientError(
            "HYPER3D_API_KEY or RODIN_API_KEY is not configured",
            "missing_api_key",
        )
    return key


def _auth_headers(*, content_type: str = "application/json") -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Accept": "application/json",
        "Content-Type": content_type,
    }


def _decode_json_response(response: Any) -> Mapping[str, Any]:
    if response.status < 200 or response.status >= 300:
        raise Hyper3DClientError(
            f"Hyper3D request failed with HTTP {response.status}",
            f"http_{response.status}",
        )
    try:
        payload = response.json()
    except Exception as exc:
        raise Hyper3DClientError("Hyper3D returned invalid JSON", "invalid_json_response") from exc
    if not isinstance(payload, Mapping):
        raise Hyper3DClientError("Hyper3D returned a non-object response", "invalid_response_shape")
    error = payload.get("error")
    if error:
        message = payload.get("message") or "Hyper3D rejected the request"
        raise Hyper3DClientError(str(message), str(error))
    return payload


def _post_json(path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    response = http_request(
        "POST",
        _api_url(path),
        headers=_auth_headers(),
        json=dict(payload),
        timeout_ms=120_000,
        max_bytes=MAX_RESPONSE_BYTES,
        raise_for_status=False,
    )
    return _decode_json_response(response)


def _multipart_body(fields: Mapping[str, str], image_paths: Sequence[Path]) -> Tuple[bytes, str]:
    boundary = f"----dcc-mcp-unreal-{uuid.uuid4().hex}"
    chunks: List[bytes] = []
    for name, value in fields.items():
        safe_name = name.replace("\r", "").replace("\n", "")
        safe_value = str(value).replace("\r", "").replace("\n", " ")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                f'Content-Disposition: form-data; name="{safe_name}"\r\n\r\n'.encode("utf-8"),
                safe_value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for image_path in image_paths:
        filename = image_path.name.replace("\r", "").replace("\n", "")
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="images"; filename="{filename}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode("utf-8"),
                image_path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _validate_images(image_paths: Iterable[str]) -> List[Path]:
    values = [str(value).strip() for value in image_paths if str(value).strip()]
    if len(values) > MAX_IMAGES:
        raise Hyper3DClientError("Hyper3D accepts at most five images", "too_many_images")
    validated: List[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise Hyper3DClientError(f"Image path does not point to an existing absolute file: {value}", "invalid_image_path")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise Hyper3DClientError(f"Image exceeds the 25 MiB limit: {value}", "image_too_large")
        validated.append(path)
    return validated


def _require_choice(value: str, name: str, choices: Sequence[str]) -> str:
    if value not in choices:
        raise Hyper3DClientError(
            f"{name} must be one of {', '.join(choices)}",
            f"invalid_{name}",
        )
    return value


def submit_generation(
    *,
    image_paths: Iterable[str] = (),
    prompt: str = "",
    tier: str = "Gen-2.5-Medium",
    mesh_mode: str = "Raw",
    quality: str = "medium",
    texture_mode: str = "",
    geometry_file_format: str = "glb",
    material: str = "PBR",
) -> Dict[str, Any]:
    images = _validate_images(image_paths)
    prompt = prompt.strip()
    if not images and not prompt:
        raise Hyper3DClientError("Provide at least one image or a non-empty prompt", "missing_generation_input")
    if images and len(images) > MAX_IMAGES:
        raise Hyper3DClientError("Hyper3D accepts at most five images", "too_many_images")
    if not images and len(prompt) > 1024:
        raise Hyper3DClientError("Text-to-3D prompt cannot exceed 1024 characters", "prompt_too_long")

    _require_choice(
        tier,
        "tier",
        (
            "Gen-2.5-Extreme-Low",
            "Gen-2.5-Low",
            "Gen-2.5-Medium",
            "Gen-2.5-High",
            "Gen-2.5-Extreme-High",
        ),
    )
    _require_choice(mesh_mode, "mesh_mode", ("Raw", "Quad"))
    _require_choice(quality, "quality", ("high", "medium", "low", "extra-low"))
    _require_choice(geometry_file_format, "geometry_file_format", ("glb", "usdz", "fbx", "obj", "stl"))
    _require_choice(material, "material", ("PBR", "Shaded", "All", "Hybrid", "None"))
    if texture_mode:
        _require_choice(texture_mode, "texture_mode", ("legacy", "extreme-low", "low", "medium", "high", "extreme-high"))

    fields = {
        "tier": tier,
        "mesh_mode": mesh_mode,
        "quality": quality,
        "geometry_file_format": geometry_file_format,
        "material": material,
    }
    if prompt:
        fields["prompt"] = prompt
    if texture_mode:
        fields["texture_mode"] = texture_mode
    body, content_type = _multipart_body(fields, images)
    headers = _auth_headers(content_type=content_type)
    response = http_request(
        "POST",
        _api_url("rodin"),
        headers=headers,
        body=body,
        timeout_ms=120_000,
        max_bytes=MAX_RESPONSE_BYTES,
        raise_for_status=False,
    )
    payload = _decode_json_response(response)
    jobs = payload.get("jobs") or {}
    if not isinstance(jobs, Mapping) or not payload.get("uuid") or not jobs.get("subscription_key"):
        raise Hyper3DClientError(
            "Hyper3D did not return a task UUID and subscription key",
            "invalid_submission_response",
        )
    return {
        "task_uuid": str(payload["uuid"]),
        "subscription_key": str(jobs["subscription_key"]),
        "job_uuids": [str(value) for value in jobs.get("uuids", []) if value],
        "consumed": payload.get("consumed"),
        "api_message": payload.get("message") or "Submitted.",
        "input_mode": "image-to-3d" if images else "text-to-3d",
    }


def generation_status(subscription_key: str) -> Dict[str, Any]:
    key = str(subscription_key).strip()
    if not key:
        raise Hyper3DClientError("subscription_key is required", "missing_subscription_key")
    payload = _post_json("status", {"subscription_key": key})
    raw_jobs = payload.get("jobs") or []
    if not isinstance(raw_jobs, list):
        raise Hyper3DClientError("Hyper3D returned an invalid jobs list", "invalid_status_response")
    jobs = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, Mapping):
            continue
        job = {
            "job_uuid": str(raw_job["uuid"]) if raw_job.get("uuid") else "",
            "status": str(raw_job.get("status", "Unknown")),
        }
        for key_name in ("progress", "message", "error"):
            if key_name in raw_job and raw_job[key_name] is not None:
                job[key_name] = raw_job[key_name]
        jobs.append(job)
    states = [job["status"] for job in jobs]
    return {
        "jobs": jobs,
        "states": states,
        "all_done": bool(states) and all(state.casefold() == "done" for state in states),
        "failed": any(state.casefold() == "failed" for state in states),
        "api_message": payload.get("message"),
    }


def _download_items(task_uuid: str) -> List[Mapping[str, Any]]:
    value = str(task_uuid).strip()
    if not value:
        raise Hyper3DClientError("task_uuid is required", "missing_task_uuid")
    payload = _post_json("download", {"task_uuid": value})
    raw_items = payload.get("list") or []
    if not isinstance(raw_items, list):
        raise Hyper3DClientError("Hyper3D returned an invalid download list", "invalid_download_response")
    items = []
    for raw_item in raw_items:
        if isinstance(raw_item, Mapping) and raw_item.get("name") and raw_item.get("url"):
            items.append({"name": str(raw_item["name"]), "url": str(raw_item["url"])})
    if not items:
        raise Hyper3DClientError("Hyper3D returned no downloadable files", "no_downloadable_result")
    return items


def download_result(task_uuid: str, result_path: str, file_name: str = "") -> Dict[str, Any]:
    destination = Path(result_path).expanduser()
    if not destination.is_absolute():
        raise Hyper3DClientError("result_path must be an absolute path", "invalid_result_path")
    items = _download_items(task_uuid)
    selected = None
    if file_name.strip():
        selected = next((item for item in items if item["name"] == file_name.strip()), None)
        if selected is None:
            raise Hyper3DClientError(f"No Hyper3D result named '{file_name}'", "result_file_not_found")
    else:
        selected = next(
            (item for item in items if Path(item["name"]).suffix.casefold() in GEOMETRY_EXTENSIONS),
            items[0],
        )
    url = str(selected["url"])
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise Hyper3DClientError("Hyper3D returned an unsafe download URL", "unsafe_download_url")
    response = http_request(
        "GET",
        url,
        headers={"Accept": "application/octet-stream"},
        timeout_ms=180_000,
        max_bytes=MAX_DOWNLOAD_BYTES,
        raise_for_status=False,
    )
    if response.status < 200 or response.status >= 300:
        raise Hyper3DClientError(
            f"Hyper3D result download failed with HTTP {response.status}",
            f"download_http_{response.status}",
        )
    written = atomic_write_bytes(destination, response.bytes, max_bytes=MAX_DOWNLOAD_BYTES)
    return {
        "task_uuid": str(task_uuid).strip(),
        "file_name": Path(str(selected["name"])).name,
        "result_path": str(written),
        "size_bytes": len(response.bytes),
    }
