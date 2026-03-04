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
