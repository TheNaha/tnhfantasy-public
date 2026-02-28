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
