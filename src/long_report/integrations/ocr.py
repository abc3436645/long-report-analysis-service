"""Configured SoMark HTTP access and source-preserving OCR normalization."""

import json
import math
import os
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml


def load_ocr_service(config_path: str | None, service_ref: str) -> dict:
    path = config_path or os.environ.get("REPORT_SERVICES_CONFIG")
    if not path:
        raise ValueError("OCR requires services_config or REPORT_SERVICES_CONFIG")
    try:
        config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("schema_version") != 1:
            raise ValueError("invalid OCR service config schema")
        service = config["services"][service_ref]
        connection = config["connections"][service["connection_ref"]]
        if (service.get("enabled") is not True or service.get("adapter") != "somark_http"
                or service.get("capability") != "document.ocr" or service.get("contract_version") != 1
                or connection.get("protocol") != "http"):
            raise ValueError("OCR service must enable document.ocr v1 with somark_http")
        endpoint = connection["endpoint"]
        url = urlsplit(endpoint)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("invalid OCR endpoint; credentials belong in auth_ref")
        auth_ref = connection["auth_ref"]
        if not isinstance(auth_ref, str) or not auth_ref.startswith("env:") or not os.environ.get(auth_ref[4:]):
            raise ValueError("OCR auth_ref requires a populated env: variable")
        binding = {"service_id": service_ref, "adapter": "somark_http", "capability": "document.ocr",
                   "contract_version": 1, "adapter_version": 1, "endpoint": endpoint.rstrip("/"), "auth_ref": auth_ref}
        proxy = connection.get("proxy")
        if proxy is not None:
            proxy_url = urlsplit(proxy) if isinstance(proxy, str) else None
            try:
                if proxy_url is not None:
                    proxy_url.port
            except ValueError:
                raise ValueError("invalid OCR proxy port") from None
            if (proxy_url is None or proxy_url.scheme not in ("http", "https") or not proxy_url.hostname
                    or proxy_url.username or proxy_url.password or proxy_url.query or proxy_url.fragment
                    or proxy_url.path not in ("", "/")):
                raise ValueError("invalid OCR proxy; use an HTTP URL without credentials")
            binding["proxy"] = proxy
        for key, default in (("timeout_seconds", 120), ("poll_interval_seconds", 2),
                             ("max_upload_bytes", 50000000), ("max_response_bytes", 20000000)):
            value = service.get(key, default)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("invalid OCR limit: " + key)
            if key.endswith("bytes") and type(value) is not int:
                raise ValueError("OCR byte limit must be an integer")
            binding[key] = value
        binding["fingerprint"] = sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        return binding
    except (KeyError, TypeError, AttributeError, yaml.YAMLError) as error:
        raise ValueError("invalid OCR service configuration") from error


def request_ocr(binding: dict, source_path: Path | None = None, task_id: str | None = None,
                mode: str = "sync", timeout: float | None = None) -> tuple[bytes, dict, str | None]:
    """One bounded request; uploads are never automatically retried or redirected."""
    key = os.environ.get(binding["auth_ref"][4:])
    if not key:
        raise ValueError("OCR credential environment variable is not set")
    data = {"api_key": key}
    if task_id:
        path = "/parse/async_check"
        data["task_id"] = task_id
    else:
        path = "/parse/" + mode
        data["output_formats"] = ["markdown", "json"]
    from contextlib import nullcontext
    file_context = source_path.open("rb") if source_path else nullcontext(None)
    raw = bytearray()
    try:
        with file_context as source, httpx.Client(timeout=timeout or binding["timeout_seconds"],
                                                follow_redirects=False, trust_env=False,
                                                proxy=binding.get("proxy")) as client:
            files = {"file": (source_path.name, source, "application/octet-stream")} if source else None
            with client.stream("POST", binding["endpoint"] + path, data=data, files=files) as response:
                for chunk in response.iter_bytes(chunk_size=65536):
                    room = binding["max_response_bytes"] - len(raw)
                    raw.extend(chunk[:room])
                    if len(chunk) > room:
                        return bytes(raw), {}, "OCR response exceeds configured byte limit (archive truncated)"
                if response.status_code != 200:
                    return bytes(raw), {}, f"OCR HTTP {response.status_code}"
        value = json.loads(raw)
        if not isinstance(value, dict) or not isinstance(value.get("data"), dict) or value.get("code") != 0:
            return bytes(raw), {}, "OCR service returned an invalid response or business error"
        return bytes(raw), value, None
    except (httpx.HTTPError, ValueError) as error:
        # Error text may contain upstream credentials or payloads; persist only its class.
        description = "OCR " + type(error).__name__
        return bytes(raw) or json.dumps({"transport_error": description}).encode(), {}, description


def transcript(response: dict, original: dict, call_id: str) -> dict:
    """Normalize zero-based SoMark pages; retain block text/HTML and coordinates."""
    data = response["data"]
    outputs = data.get("result", {}).get("outputs", {})
    pages = outputs.get("json", {}).get("pages")
    markdown = outputs.get("markdown")
    count = original["parsed"]["coverage"]["page_count"]
    if (data.get("error") or type(data.get("metadata", {}).get("page_num")) is not int
            or data["metadata"]["page_num"] != count or not isinstance(pages, list) or not isinstance(markdown, str)):
        raise ValueError("OCR result requires matching page metadata, Markdown and JSON pages")
    requested = original["parsed"]["coverage"]["unread_pages"]
    lines = [f"<!-- OCR source={original['fingerprint']} call={call_id}; unverified transcription -->"]
    fragments, mapping, block_map, seen, read = [], {}, {}, set(), set()
    for page in pages:
        if not isinstance(page, dict) or type(page.get("page_num")) is not int:
            raise ValueError("invalid OCR page number")
        number = page["page_num"] + 1
        if not 1 <= number <= count or number in seen or not isinstance(page.get("blocks"), list):
            raise ValueError("invalid or duplicate OCR page")
        seen.add(number)
        if number not in requested:
            continue
        size = page.get("page_size", {})
        if any(type(size.get(k)) not in (int, float) or not math.isfinite(size[k]) or size[k] <= 0 for k in ("w", "h")):
            raise ValueError("invalid OCR page size")
        indices = set()
        for block in page["blocks"]:
            if not isinstance(block, dict) or not isinstance(block.get("content"), str) or type(block.get("idx")) is not int:
                raise ValueError("invalid OCR text block")
            box = block.get("bbox")
            if (block["idx"] in indices or block["idx"] < 0 or not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                    or not 0 <= box[0] <= box[2] <= size["w"] or not 0 <= box[1] <= box[3] <= size["h"]):
                raise ValueError("invalid OCR block coordinates or index")
            indices.add(block["idx"])
            for line in block["content"].splitlines():
                if not line.strip():
                    continue
                lines.append(line)
                locator = f"line:{len(lines)}"
                fragments.append({"value": line, "locator": locator})
                mapping[locator] = f"page:{number}"
                block_map[locator] = {"page": number, "block": block["idx"], "bbox": box,
                                      "page_size": size, "type": block.get("type"), "format": block.get("format")}
                read.add(number)
    missing = sorted(set(requested) - read)
    return {"text": ("\n".join(lines) + "\n").encode(), "markdown": markdown.encode(),
            "json": json.dumps(outputs["json"], ensure_ascii=False, indent=2).encode(),
            "locator_map": mapping, "block_map": block_map,
            "status": "empty" if not fragments else "partial" if missing else "succeeded",
            "parsed": {"fragments": fragments, "coverage": {"page_count": count, "requested_pages": requested,
                "unread_pages": missing, "content_verified": False,
                "pages": [{"page": p, "status": "ocr_text_obtained" if p in read else "unread"} for p in requested]}}}
