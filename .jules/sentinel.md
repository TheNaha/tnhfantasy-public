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

## 2025-10-26 - [Path Traversal in Provider Worker Apps]
**Vulnerability:** Found path traversal vulnerabilities in `provider_containers/modal_worker/modal_app.py` and `provider_containers/beam_worker/beam_app.py`.
**Learning:** External inputs like `path` and `directory` were being passed directly to `os.path.join(base_path, user_input)`. This permitted attackers to use absolute paths or `../` to break out of the intended `/mnt/data` directory and interact with arbitrary files.
**Prevention:** Always use `get_safe_path(base_path, user_input)` from shared utilities before performing any file system operations (like downloading, validating, or verifying files). Handle the potential exception raised by `get_safe_path` when a malicious path is detected, returning a generic error to the caller without exposing system details or stack traces.

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
## 2025-03-12 - Fix URL Parameter Injection (SSRF Risk) in External API Proxy
**Vulnerability:** User-provided search queries were directly concatenated into external API URLs (`https://civitai.com/...` and `https://huggingface.co/...`) without URL encoding, allowing users to inject arbitrary URL parameters (Parameter Injection) which can lead to Server-Side Request Forgery (SSRF) and broken API requests.
**Learning:** Even when proxying requests to safe external domains (not internal workers), direct string interpolation of user input into URLs introduces parameter injection vulnerabilities.
**Prevention:** Always URL-encode user-provided input using `urllib.parse.quote(query, safe='')` before appending it to a URL query string.
## 2025-05-21 - [SSRF Parameter Injection in Provider Worker Proxies]
**Vulnerability:** The `list_models` internal provider methods for `ModalProvider` and `BeamProvider` passed the user-provided `directory` string directly into the worker proxy URL (`f"{self.worker_url}/list-models?directory={directory}"`) without URL encoding.
**Learning:** Internal service-to-service calls must rigorously encode dynamically substituted path and query parameters, particularly when proxying external user inputs to avoid Parameter Injection/SSRF on internal networks. Unencoded characters (like `&` and `=`) allow attackers to manipulate queries to upstream services.
**Prevention:** Ensure that all dynamically injected query parameters to downstream services are properly encoded using `urllib.parse.quote(param, safe='')`.

## 2025-02-29 - [Command Injection Risk via shell=True]
**Vulnerability:** The application used `subprocess.Popen(..., shell=True)` to launch the ComfyUI server in `modal_app.py` and `beam_app.py`.
**Learning:** Using `shell=True` allows the shell to interpret the command string, which can lead to command injection if any part of the command string is user-controlled. Even if the current usage seems safe (e.g., interpolating an integer port), it's a dangerous pattern that should be avoided.
**Prevention:** Always pass arguments to `subprocess.Popen` as a list of strings and omit `shell=True` (which defaults to `False`). This ensures the command and its arguments are passed directly to the OS, bypassing the shell and eliminating the risk of command injection.

## 2025-03-21 - [Path Traversal in Model Listing]
**Vulnerability:** The `list_models_with_metadata` and `list_models` functions in `modal_app.py` and `beam_app.py` respectively were vulnerable to path traversal. They directly concatenated user-provided `directory` input with the base path using `os.path.join()`.
**Learning:** While other methods in these files properly used `get_safe_path()`, these list endpoints were missed, demonstrating that every single endpoint that handles file paths must be secured. `os.path.join()` is fundamentally unsafe for joining trusted base paths with untrusted user input because absolute paths or `../` in the user input can escape the base directory.
**Prevention:** Always use a utility like `get_safe_path()` that explicitly checks for and prevents path traversal (e.g., by checking `os.path.commonpath()`) instead of relying on standard path joining functions when dealing with user input.
## 2025-02-14 - Fix Cross-Site Scripting (XSS) in HTML rendering
**Vulnerability:** Arbitrary external HTML from API responses (such as model descriptions and version notes) was rendered directly into the DOM using `dangerouslySetInnerHTML` without sanitization. This allowed any script embedded in those third-party inputs to execute in the user's browser.
**Learning:** `dangerouslySetInnerHTML` passes raw HTML directly to the browser. Any text containing `<script>` or event handlers (like `onerror`) can execute arbitrary code. React's default XSS protection does not apply when explicitly using `dangerouslySetInnerHTML`.
**Prevention:** Always sanitize strings before passing them to `dangerouslySetInnerHTML`. Use established sanitization libraries like `DOMPurify` (e.g., `DOMPurify.sanitize(userInput)`) to strip out malicious content while preserving safe HTML formatting.
