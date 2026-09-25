#!/usr/bin/env python3
"""Populate download_url values from the CivitAI API."""

import argparse
import os
import time
from collections.abc import Sequence

import httpx
from sqlalchemy import create_engine, text

CIVITAI_API = "https://civitai.com/api/v1/models"
BATCH_DELAY = 0.3


def fetch_civitai_model(model_id: int, token: str | None = None) -> dict | None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = httpx.get(f"{CIVITAI_API}/{model_id}", headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"  WARNING: Failed to fetch CivitAI model {model_id}: {exc}")
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("COMFY_DATABASE_URL", "sqlite:///./data/comfy.db"),
    )
    args = parser.parse_args(argv)
    engine = create_engine(args.database_url)

    with engine.begin() as connection:
        files = connection.execute(text("""
            SELECT mf.id AS file_id,
                   mv.civitai_version_id,
                   m.civitai_model_id,
                   m.name AS model_name
            FROM model_files mf
            JOIN model_versions mv ON mf.version_id = mv.id
            JOIN models_v2 m ON mv.model_id = m.id
            WHERE (mf.download_url IS NULL OR mf.download_url = '')
              AND mv.civitai_version_id IS NOT NULL
            ORDER BY m.civitai_model_id
        """)).mappings().all()
        print(f"Found {len(files)} files with missing download_url and civitai_version_id")
        if not files:
            return 0

        by_model: dict[int, list[dict]] = {}
        for file_row in files:
            by_model.setdefault(file_row["civitai_model_id"], []).append(dict(file_row))
        print(f"Covers {len(by_model)} unique CivitAI models")

        token = os.getenv("CIVITAI_TOKEN")
        updated = 0
        skipped = 0
        failed = 0
        for civitai_id, model_files in by_model.items():
            print(f"\nCivitAI model {civitai_id} ({model_files[0]['model_name']})...")
            data = fetch_civitai_model(civitai_id, token)
            if not data:
                failed += len(model_files)
                continue

            version_url_map: dict[int, str] = {}
            for version in data.get("modelVersions", []):
                version_id = version.get("id")
                if not version_id:
                    continue
                version_files = version.get("files", [])
                primary = next(
                    (item for item in version_files if item.get("primary")),
                    version_files[0] if version_files else None,
                )
                if primary and primary.get("downloadUrl"):
                    version_url_map[version_id] = primary["downloadUrl"]
                elif version.get("downloadUrl"):
                    version_url_map[version_id] = version["downloadUrl"]

            matched = 0
            for file_row in model_files:
                download_url = version_url_map.get(file_row["civitai_version_id"])
                if not download_url:
                    skipped += 1
                    continue
                connection.execute(
                    text("UPDATE model_files SET download_url = :download_url WHERE id = :file_id"),
                    {"download_url": download_url, "file_id": file_row["file_id"]},
                )
                updated += 1
                matched += 1
            if matched:
                print(f"  Matched {matched}/{len(model_files)} files")
            time.sleep(BATCH_DELAY)

        print(f"\nDone: {updated} updated, {skipped} skipped, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
