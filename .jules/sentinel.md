## 2025-01-27 - [Path Traversal in File API]
**Vulnerability:** Path traversal vulnerability in `backend_v2/api/routes/files.py` allowed arbitrary file read/write via `view_file_endpoint` and `upload_file_endpoint` using `..` in paths.
**Learning:** FastAPI/Starlette path parameters (`{path:path}`) capture the raw path including slashes but do not resolve `..`. If passed directly to `os.path.join`, traversal is possible. `os.path.join` with an absolute path component (e.g. `/etc/passwd`) discards previous components, leading to full filesystem access.
**Prevention:** Always use a helper like `get_safe_path` that resolves the path and checks `os.path.commonpath` against the intended base directory. Strip leading slashes from user input before joining.
