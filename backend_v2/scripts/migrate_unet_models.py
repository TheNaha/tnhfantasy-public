#!/usr/bin/env python
"""
Migrate UNET-only models (Flux, AuraFlow, Pony V7) from 'checkpoints' to 'unet' directory.
Usage: python scripts/migrate_unet_models.py
"""
import os
import sys

# Ensure we can import from backend_v2
sys.path.insert(0, os.getcwd())

from api.deps import get_session_sync
from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2


def main():
    print("Starting UNET model migration...")
    try:
        with get_session_sync() as session:
            repo = ModelRepositoryV2(session)
            result = repo.migrate_unet_only_models()

        print("Migration complete.")
        print(f"Migrated {result['count']} models to unet directory.")
        if result['migrated']:
            for m in result['migrated']:
                print(f" - Moved {m['name']} (Base: {m['base_model']}) from {m['old_directory']} to {m['new_directory']}")
    except Exception as e:
        if "no such table" in str(e):
            print("Database not initialized or tables missing. Skipping migration.")
        else:
            print(f"Error during migration: {e}")

if __name__ == "__main__":
    main()
