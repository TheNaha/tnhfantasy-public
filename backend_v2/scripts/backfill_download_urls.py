#!/usr/bin/env python3
"""One-time backfill: populate download_url using civitai_version_id.

The CivitAI API returns modelVersions[].files[].downloadUrl.
Our DB has ModelVersion.civitai_version_id matching modelVersions[].id.
Match by version ID, then look up the file's download URL.

Usage:
    docker exec tnhcomfy-backend python3 scripts/backfill_download_urls.py
"""
import os
import sqlite3
import time
import httpx

DB_PATH = os.environ.get("COMFY_DATABASE_URL", "sqlite:///./data/db/comfy.db")
if DB_PATH.startswith("sqlite:///"):
    DB_PATH = DB_PATH[len("sqlite:///"):]

CIVITAI_API = "https://civitai.com/api/v1/models"
BATCH_DELAY = 0.3  # seconds between API calls


def fetch_civitai_model(model_id: int, token: str | None = None) -> dict | None:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(f"{CIVITAI_API}/{model_id}", headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  WARNING: Failed to fetch civitai model {model_id}: {e}")
        return None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Find files missing download_url that have a civitai_version_id
    cur.execute("""
        SELECT mf.id AS file_id,
               mf.original_filename,
               mf.download_url,
               mv.id AS version_id,
               mv.civitai_version_id,
               m.civitai_model_id,
               m.name AS model_name
        FROM model_files mf
        JOIN model_versions mv ON mf.version_id = mv.id
        JOIN models_v2 m ON mv.model_id = m.id
        WHERE (mf.download_url IS NULL OR mf.download_url = '')
          AND mv.civitai_version_id IS NOT NULL
        ORDER BY m.civitai_model_id
    """)
    files = cur.fetchall()
    print(f"Found {len(files)} files with missing download_url and civitai_version_id")

    if not files:
        print("Nothing to backfill.")
        conn.close()
        return

    # Group by civitai_model_id to minimize API calls
    by_model: dict[int, list] = {}
    for f in files:
        cid = f["civitai_model_id"]
        if cid not in by_model:
            by_model[cid] = []
        by_model[cid].append(f)

    print(f" Covers {len(by_model)} unique CivitAI models")

    token = os.environ.get("CIVITAI_TOKEN")
    updated = 0
    skipped = 0
    failed = 0

    for civitai_id, model_files in by_model.items():
        print(f"\nCivitAI model {civitai_id} ({model_files[0]['model_name']})...")
        data = fetch_civitai_model(civitai_id, token)
        if not data:
            failed += len(model_files)
            continue

        # Build civitai_version_id -> download_url map
        # Each version has files[].downloadUrl; use the primary file's URL
        version_url_map: dict[int, str] = {}
        for version in data.get("modelVersions", []):
            vid = version.get("id")
            if not vid:
                continue
            # Prefer the primary file's downloadUrl
            vfiles = version.get("files", [])
            primary = next((f for f in vfiles if f.get("primary")), vfiles[0] if vfiles else None)
            if primary and primary.get("downloadUrl"):
                version_url_map[vid] = primary["downloadUrl"]
            # Fallback: version-level downloadUrl
            elif version.get("downloadUrl"):
                version_url_map[vid] = version["downloadUrl"]

        matched = 0
        for mf in model_files:
            civitai_vid = mf["civitai_version_id"]
            download_url = version_url_map.get(civitai_vid)
            if download_url:
                cur.execute(
                    "UPDATE model_files SET download_url = ? WHERE id = ?",
                    (download_url, mf["file_id"]),
                )
                updated += 1
                matched += 1
            else:
                skipped += 1
                print(f"  - version {civitai_vid} not found in API response")

        if matched:
            print(f"  ✓ {matched}/{len(model_files)} files matched")

        time.sleep(BATCH_DELAY)

    conn.commit()
    conn.close()
    print(f"\nDone: {updated} updated, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    main()
