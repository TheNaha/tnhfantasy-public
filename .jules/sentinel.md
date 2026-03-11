## 2025-01-27 - [Path Traversal in File API]
**Vulnerability:** Path traversal vulnerability in `backend_v2/api/routes/files.py` allowed arbitrary file read/write via `view_file_endpoint` and `upload_file_endpoint` using `..` in paths.
**Learning:** FastAPI/Starlette path parameters (`{path:path}`) capture the raw path including slashes but do not resolve `..`. If passed directly to `os.path.join`, traversal is possible. `os.path.join` with an absolute path component (e.g. `/etc/passwd`) discards previous components, leading to full filesystem access.
**Prevention:** Always use a helper like `get_safe_path` that resolves the path and checks `os.path.commonpath` against the intended base directory. Strip leading slashes from user input before joining.
## 2025-02-28 - [Path Traversal in Provider Containers]
**Vulnerability:** Found multiple path traversal vulnerabilities in `beam_app.py` and `modal_app.py` file storage endpoints.
**Learning:** File paths passed from external inputs (e.g., via API endpoints or `Request` bodies) to file operations (`open`, `os.remove`, `os.path.getsize`) without proper sanitization allow arbitrary read/write/delete operations on the container's file system. For instance, concatenating strings using `os.path.join("/mnt/data", path)` is unsafe because if `path` begins with a slash or contains `../`, it can escape the intended directory.
**Prevention:** Implement and enforce the use of a `get_safe_path` utility function across all file operations. This function should:
1. Deny empty paths.
2. Strip leading slashes from requested paths.
3. Use `os.path.abspath(os.path.join(base_dir, clean_path))` to resolve the final path.
4. Verify the resolved path remains strictly within the intended base directory using `os.path.commonpath([base_path, full_path]) == base_path`.

## 2025-05-18 - [Path Traversal in Model List]
**Vulnerability:** The API endpoint `GET /api/files?directory=models/{model_type}` passes `model_type` into `os.path.join(CACHE_DIR, "models", model_type)` without path sanitization inside `_scan_local_model_directory`. This allows an attacker to bypass the directory restrictions and list arbitrary directories on the server using `..` like `models/../../../etc`.
**Learning:** Even if a global `get_safe_path` utility exists in the module, it must be consistently applied to all paths formed from user input, even in background threads/functions like `_scan_local_model_directory` that handle fallback/legacy functionality.
**Prevention:** Always wrap user-provided subpaths with `get_safe_path` before checking if the path exists or using `os.listdir`, preventing attackers from "breaking out" of the intended base directory.
## 2025-02-18 - Path Traversal via os.path.join Absolute Path Injection
**Vulnerability:** Multiple API endpoints in `backend_v2/api/routes/files.py` (e.g., `view_file_endpoint`, `serve_thumbnail`, `batch_delete_endpoint`, `batch_get_metadata`) were vulnerable to absolute path injection.
**Learning:** In Python, `os.path.join(base, user_input)` discards the `base` path if `user_input` starts with a slash (e.g., `/etc/passwd`), resulting in an absolute path that bypasses intended directory restrictions. Even if `get_safe_path` is called to validate the path initially, using the original un-sanitized string with `os.path.join` or `glob.glob` later in the same function re-introduces the vulnerability.
**Prevention:** Always sanitize user-provided path components by explicitly stripping leading slashes (e.g., `filename = filename.lstrip("/\\")`) *before* passing them to `os.path.join` or `glob.glob`, or consistently use the sanitized absolute path returned by validation functions like `get_safe_path`.
## 2025-05-20 - [SSRF Parameter Injection in Provider Proxies]
**Vulnerability:** The `/api/files/proxy/{provider_id}/{path:path}` endpoint in `backend_v2/api/routes/files.py` passed the user-provided `path` directly into the worker's proxy URL (`f"{self.base_url}/file-proxy?path={path}"`) without URL encoding.
**Learning:** When constructing URLs from user input, even if the input appears to be a "path", failing to URL encode it allows an attacker to inject arbitrary query parameters (e.g., `image.png&other_param=malicious_value`). In a server-side request context, this leads to parameter injection and potentially Server-Side Request Forgery (SSRF) against the internal worker API.
**Prevention:** Always use `urllib.parse.quote` (or equivalent) to URL-encode user-provided data before embedding it into the query string of an outgoing HTTP request.
## 2025-05-21 - [SSRF Parameter Injection in Provider Worker Proxies]
**Vulnerability:** The `list_models` internal provider methods for `ModalProvider` and `BeamProvider` passed the user-provided `directory` string directly into the worker proxy URL (`f"{self.worker_url}/list-models?directory={directory}"`) without URL encoding.
**Learning:** Internal service-to-service calls must rigorously encode dynamically substituted path and query parameters, particularly when proxying external user inputs to avoid Parameter Injection/SSRF on internal networks. Unencoded characters (like `&` and `=`) allow attackers to manipulate queries to upstream services.
**Prevention:** Ensure that all dynamically injected query parameters to downstream services are properly encoded using `urllib.parse.quote(param, safe='')`.