#!/usr/bin/env python
"""
Run migration from V1 to V2 model schema.
Usage: python scripts/migrate_models_v2.py
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text, inspect, create_engine
import json

def migrate_models_to_v2():
    """Migrate models from V1 to V2 schema."""
    from core.entities_v2 import compute_storage_filename
    
    engine = create_engine('sqlite:///data/comfy.db', connect_args={'check_same_thread': False})
    
    with engine.connect() as conn:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'models' not in tables or 'models_v2' not in tables:
            print("Required tables not found")
            return
        
        # Check counts
        result = conn.execute(text("SELECT COUNT(*) FROM models_v2"))
        v2_count = result.scalar()
        if v2_count > 0:
            print(f"V2 already has {v2_count} models, skipping migration")
            return
        
        result = conn.execute(text("SELECT COUNT(*) FROM models"))
        v1_count = result.scalar()
        if v1_count == 0:
            print("No V1 models to migrate")
            return
        
        print(f"Migrating {v1_count} models from V1 to V2...")
        
        # Fetch all V1 models
        result = conn.execute(text("""
            SELECT id, name, directory, url, source, metadata_, provider_statuses, 
                   created_at, updated_at
            FROM models
        """))
        rows = result.fetchall()
        
        migrated = 0
        for row in rows:
            try:
                metadata = json.loads(row[5]) if row[5] else {}
                provider_statuses = json.loads(row[6]) if row[6] else {}
                
                if not metadata:
                    continue
                
                civitai_id = metadata.get("id")
                stats = metadata.get("stats", {})
                creator = metadata.get("creator", {})
                
                # Insert model
                conn.execute(text("""
                    INSERT INTO models_v2 (
                        civitai_model_id, name, type, directory, description,
                        nsfw, nsfw_level, creator_username, creator_image,
                        stats_downloads, stats_thumbs_up, stats_thumbs_down, stats_comments,
                        source, source_url, created_at, updated_at
                    ) VALUES (
                        :civitai_id, :name, :type, :directory, :description,
                        :nsfw, :nsfw_level, :creator_username, :creator_image,
                        :downloads, :thumbs_up, :thumbs_down, :comments,
                        :source, :url, :created_at, :updated_at
                    )
                """), {
                    "civitai_id": civitai_id,
                    "name": metadata.get("name", row[1]),
                    "type": metadata.get("type", "Checkpoint"),
                    "directory": row[2],
                    "description": metadata.get("description"),
                    "nsfw": metadata.get("nsfw", False),
                    "nsfw_level": metadata.get("nsfwLevel", 1),
                    "creator_username": creator.get("username"),
                    "creator_image": creator.get("image"),
                    "downloads": stats.get("downloadCount", 0),
                    "thumbs_up": stats.get("thumbsUpCount", 0),
                    "thumbs_down": stats.get("thumbsDownCount", 0),
                    "comments": stats.get("commentCount", 0),
                    "source": row[4] or "civitai",
                    "url": row[3],
                    "created_at": row[7],
                    "updated_at": row[8]
                })
                
                # Get model ID
                model_result = conn.execute(text(
                    "SELECT id FROM models_v2 WHERE civitai_model_id = :cid"
                ), {"cid": civitai_id})
                model_v2_id = model_result.scalar()
                
                if not model_v2_id:
                    continue
                
                # Tags
                for tag in metadata.get("tags", []):
                    try:
                        conn.execute(text(
                            "INSERT INTO model_tags (model_id, tag) VALUES (:model_id, :tag)"
                        ), {"model_id": model_v2_id, "tag": tag})
                    except Exception:
                        pass
                
                # Versions - take first only
                versions = metadata.get("modelVersions", [])
                if not versions:
                    continue
                
                version_data = versions[0]
                civitai_version_id = version_data.get("id")
                trained_words = version_data.get("trainedWords", [])
                trained_words_json = json.dumps(trained_words) if trained_words else None
                
                conn.execute(text("""
                    INSERT INTO model_versions (
                        model_id, civitai_version_id, name, base_model, base_model_type,
                        description, is_enabled, is_default, trained_words,
                        civitai_published_at, created_at
                    ) VALUES (
                        :model_id, :civitai_version_id, :name, :base_model, :base_model_type,
                        :description, 1, 1, :trained_words,
                        :published_at, :created_at
                    )
                """), {
                    "model_id": model_v2_id,
                    "civitai_version_id": civitai_version_id,
                    "name": version_data.get("name", "v1.0"),
                    "base_model": version_data.get("baseModel"),
                    "base_model_type": version_data.get("baseModelType"),
                    "description": version_data.get("description"),
                    "trained_words": trained_words_json,
                    "published_at": version_data.get("publishedAt"),
                    "created_at": row[7]
                })
                
                version_result = conn.execute(text(
                    "SELECT id FROM model_versions WHERE civitai_version_id = :vid"
                ), {"vid": civitai_version_id})
                version_id = version_result.scalar()
                
                if not version_id:
                    continue
                
                # Files
                files = version_data.get("files", [])
                for i, file_data in enumerate(files):
                    hashes = file_data.get("hashes", {})
                    storage_filename = compute_storage_filename(
                        metadata.get("name", "model"),
                        version_data.get("name", "v1"),
                        civitai_version_id,
                        file_data.get("name", "model.safetensors")
                    )
                    
                    conn.execute(text("""
                        INSERT INTO model_files (
                            version_id, civitai_file_id, original_filename, storage_filename,
                            size_kb, format, hash_sha256, hash_autov2, hash_blake3, hash_crc32,
                            download_url, is_primary, file_type
                        ) VALUES (
                            :version_id, :civitai_file_id, :original_filename, :storage_filename,
                            :size_kb, :format, :sha256, :autov2, :blake3, :crc32,
                            :download_url, :is_primary, :file_type
                        )
                    """), {
                        "version_id": version_id,
                        "civitai_file_id": file_data.get("id"),
                        "original_filename": file_data.get("name", "model.safetensors"),
                        "storage_filename": storage_filename,
                        "size_kb": file_data.get("sizeKB", 0),
                        "format": file_data.get("metadata", {}).get("format") if file_data.get("metadata") else None,
                        "sha256": hashes.get("SHA256"),
                        "autov2": hashes.get("AutoV2"),
                        "blake3": hashes.get("BLAKE3"),
                        "crc32": hashes.get("CRC32"),
                        "download_url": file_data.get("downloadUrl"),
                        "is_primary": file_data.get("primary", i == 0),
                        "file_type": file_data.get("type", "Model")
                    })
                
                # Get primary file ID
                file_result = conn.execute(text(
                    "SELECT id FROM model_files WHERE version_id = :vid AND is_primary = 1"
                ), {"vid": version_id})
                file_id = file_result.scalar()
                
                # Provider statuses
                if file_id and provider_statuses:
                    for provider_name, status_data in provider_statuses.items():
                        old_status = status_data.get("status", "pending")
                        status_map = {"installed": "ready", "downloading": "downloading", "failed": "failed"}
                        new_status = status_map.get(old_status, "pending")
                        
                        conn.execute(text("""
                            INSERT INTO provider_version_status (
                                file_id, provider_id, provider_name, status, storage_path, size_bytes,
                                downloaded_at, queued_at, retry_count
                            ) VALUES (
                                :file_id, :provider_id, :provider_name, :status, :storage_path, :size_bytes,
                                :downloaded_at, datetime('now'), 0
                            )
                        """), {
                            "file_id": file_id,
                            "provider_id": provider_name,
                            "provider_name": provider_name,
                            "status": new_status,
                            "storage_path": f"{row[2]}/{row[1]}",
                            "size_bytes": status_data.get("size_bytes"),
                            "downloaded_at": status_data.get("updated_at")
                        })
                
                # Images
                images = version_data.get("images", [])
                for i, img_data in enumerate(images):
                    conn.execute(text("""
                        INSERT INTO model_images (
                            version_id, url, width, height, blurhash, type,
                            nsfw_level, has_meta, has_positive_prompt, sort_order
                        ) VALUES (
                            :version_id, :url, :width, :height, :blurhash, :type,
                            :nsfw_level, :has_meta, :has_positive_prompt, :sort_order
                        )
                    """), {
                        "version_id": version_id,
                        "url": img_data.get("url"),
                        "width": img_data.get("width"),
                        "height": img_data.get("height"),
                        "blurhash": img_data.get("hash"),
                        "type": img_data.get("type", "image"),
                        "nsfw_level": img_data.get("nsfwLevel", 1),
                        "has_meta": img_data.get("hasMeta", False),
                        "has_positive_prompt": img_data.get("hasPositivePrompt", False),
                        "sort_order": i
                    })
                
                migrated += 1
                if migrated % 20 == 0:
                    print(f"  Migrated {migrated} models...")
                
            except Exception as e:
                print(f"Error migrating model {row[1]}: {e}")
                continue
        
        conn.commit()
        print(f"✓ Successfully migrated {migrated} models to V2 schema")


if __name__ == "__main__":
    migrate_models_to_v2()
